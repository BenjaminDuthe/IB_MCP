import os
import json
import logging
import asyncio
import re
from typing import Optional
import anthropic

from telegram_bot.mcp_clients import MCPClientManager
from telegram_bot.models import TradeSignal, TradeAction
from telegram_bot.db import insert_analysis_log

logger = logging.getLogger(__name__)

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

SYSTEM_PROMPT = """Tu es un assistant de trading professionnel connecte a Interactive Brokers.
Tu as acces aux donnees de marche en temps reel, a l'analyse de sentiment, aux actualites financieres et a la possibilite de passer des ordres via IB.

IMPORTANT - FORMAT DE REPONSE :
- Reponds TOUJOURS en francais
- Utilise le formatage HTML Telegram : <b>gras</b>, <i>italique</i>, <code>code</code>
- N'utilise JAMAIS de markdown (pas de **, ##, -, * etc.)
- Utilise des emojis pour structurer (📈 📉 🔴 🟢 ⚠️ 💰 📊)
- Sois TRES CONCIS : 10-15 lignes max
- L'utilisateur est debutant en bourse, explique simplement
- Termine TOUJOURS par un verdict clair du type :
  "🟢 OUI, bon moment pour acheter X a $Y parce que Z"
  ou "🔴 NON, evite d'acheter X parce que Z"
  ou "⚠️ ATTENDS, le moment n'est pas ideal parce que Z"

Ton role :
1. Analyser l'action avec les sources disponibles
2. Donner un verdict simple : acheter, vendre, ou attendre
3. Expliquer en 1-2 phrases POURQUOI, comme si tu parlais a un ami
4. Si tu recommandes un achat, donne le prix et un stop-loss (= prix ou tu revends pour limiter les pertes)
5. Ne JAMAIS passer d'ordres directement. Generer des signaux necessitant approbation humaine.

Pour generer un signal de trade, utilise ce format JSON exact dans ta reponse :
```trade_signal
{"ticker": "AAPL", "action": "BUY", "quantity": 10, "order_type": "LMT", "price": 185.50, "confidence": 72, "reason": "Fondamentaux solides...", "stop_loss": 180.00, "take_profit": 195.00}
```
Les blocs trade_signal seront automatiquement retires du texte affiche a l'utilisateur.
Mets-les a la FIN de ta reponse, apres ton analyse.

SOURCES :
- Quand tu cites un article ou un post, inclus le lien en HTML : <a href="URL">titre</a>
- Ajoute une section 📎 Sources a la fin avec les liens les plus pertinents (max 3-5)
- Ne fabrique JAMAIS d'URL. Utilise uniquement les URLs presentes dans les resultats des outils.
- Si aucun outil n'a retourne d'URL, n'invente pas de section Sources.

Regles de gestion du risque :
- Toujours suggerer un stop-loss pour les ordres BUY
- Ne jamais suggerer plus de 25% du portfolio sur une seule position
- Prendre en compte les conditions de marche et la volatilite
- Considerer les positions existantes pour eviter la surconcentration
"""


class Orchestrator:
    """Bridge between Claude API and MCP tools. Handles the agentic loop."""

    def __init__(self, mcp_manager: MCPClientManager):
        self.mcp = mcp_manager
        self.client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    async def _call_claude_with_retry(self, **kwargs) -> anthropic.types.Message:
        """Call Claude API with retry on rate limit (429) errors."""
        max_retries = 4
        for attempt in range(max_retries + 1):
            try:
                return await self.client.messages.create(**kwargs)
            except anthropic.RateLimitError as e:
                if attempt == max_retries:
                    raise
                wait = 30 * (attempt + 1)  # 30s, 60s, 90s, 120s
                logger.warning(f"Rate limit hit (attempt {attempt + 1}/{max_retries + 1}), waiting {wait}s...")
                await asyncio.sleep(wait)

    async def process_message(
        self,
        user_message: str,
        ticker: Optional[str] = None,
        trigger_type: str = "user",
    ) -> tuple[str, list[TradeSignal]]:
        """Process a user message through Claude with MCP tools.

        Returns (response_text, list_of_trade_signals).
        """
        tools = self.mcp.get_claude_tool_definitions()
        messages = [{"role": "user", "content": user_message}]

        all_tools_used = []
        collected_sources: list[dict] = []  # [{"title": "...", "url": "..."}]
        total_input_tokens = 0
        total_output_tokens = 0

        # Agentic loop: let Claude call tools until it produces a final response
        max_iterations = 15
        for _ in range(max_iterations):
            response = await self._call_claude_with_retry(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=tools,
                messages=messages,
            )

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            # Check if Claude wants to use tools
            if response.stop_reason == "tool_use":
                # Process all tool calls in this response
                assistant_content = response.content
                messages.append({"role": "assistant", "content": assistant_content})

                tool_results = []
                for block in assistant_content:
                    if block.type == "tool_use":
                        tool_name = block.name
                        tool_input = block.input
                        all_tools_used.append(tool_name)

                        logger.info(f"Calling tool: {tool_name} with {json.dumps(tool_input)[:200]}")

                        try:
                            result = await self.mcp.call_tool(tool_name, tool_input)
                            result_text = json.dumps(result) if isinstance(result, (dict, list)) else str(result)
                            # Collect source URLs from tool results
                            collected_sources.extend(self._extract_source_urls(result))
                            # Truncate very large results
                            if len(result_text) > 8000:
                                result_text = result_text[:8000] + "\n... (truncated)"
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result_text,
                            })
                        except Exception as e:
                            logger.error(f"Tool call failed: {tool_name}: {e}")
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": f"Error calling tool: {str(e)}",
                                "is_error": True,
                            })

                messages.append({"role": "user", "content": tool_results})
            else:
                # Final response - extract text
                response_text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        response_text += block.text

                # Extract trade signals from response
                signals = self._extract_trade_signals(response_text)
                # Strip trade_signal blocks from displayed text
                response_text = self._strip_trade_signal_blocks(response_text)

                # Fallback: append sources if Claude didn't include any
                if collected_sources and '<a href=' not in response_text:
                    response_text = self._append_sources_footer(response_text, collected_sources)

                # Log the analysis
                await insert_analysis_log(
                    trigger_type=trigger_type,
                    ticker=ticker,
                    prompt=user_message[:2000],
                    response=response_text[:5000],
                    tools_used=all_tools_used,
                    tokens_input=total_input_tokens,
                    tokens_output=total_output_tokens,
                )

                return response_text, signals

        # Safety: if we hit max iterations, return what we have
        return "Analysis reached maximum tool call iterations. Please try a more specific request.", []

    def _extract_trade_signals(self, text: str) -> list[TradeSignal]:
        """Extract trade signal JSON blocks from Claude's response."""
        signals = []
        marker = "```trade_signal"
        parts = text.split(marker)

        for i in range(1, len(parts)):
            part = parts[i]
            end = part.find("```")
            if end == -1:
                continue
            json_str = part[:end].strip()
            try:
                data = json.loads(json_str)
                signal = TradeSignal(
                    ticker=data["ticker"],
                    action=TradeAction(data["action"]),
                    quantity=data.get("quantity"),
                    order_type=data.get("order_type"),
                    price=data.get("price"),
                    confidence=data.get("confidence"),
                    reason=data.get("reason"),
                    stop_loss=data.get("stop_loss"),
                    take_profit=data.get("take_profit"),
                )
                signals.append(signal)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"Failed to parse trade signal: {e}")

        return signals

    @staticmethod
    def _strip_trade_signal_blocks(text: str) -> str:
        """Remove ```trade_signal ... ``` blocks from displayed text."""
        cleaned = re.sub(r'```trade_signal\s*\{.*?\}\s*```', '', text, flags=re.DOTALL)
        # Clean up multiple blank lines left by removal
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        return cleaned.strip()

    @staticmethod
    def _extract_source_urls(result) -> list[dict]:
        """Extract source URLs from MCP tool results."""
        sources = []
        if not isinstance(result, (dict, list)):
            return sources

        items = []
        if isinstance(result, dict):
            # Finnhub news: {"articles": [...]}
            items.extend(result.get("articles", []))
            # Reddit: {"top_posts": [...]}
            items.extend(result.get("top_posts", []))
            # Combined sentiment: {"reddit": {"top_posts": [...]}, ...}
            reddit_data = result.get("reddit", {})
            if isinstance(reddit_data, dict):
                items.extend(reddit_data.get("top_posts", []))
            # MCP content wrapper: {"content": [{"text": "..."}]}
            content = result.get("content", [])
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and "text" in c:
                        try:
                            parsed = json.loads(c["text"])
                            if isinstance(parsed, dict):
                                items.extend(parsed.get("articles", []))
                                items.extend(parsed.get("top_posts", []))
                                rd = parsed.get("reddit", {})
                                if isinstance(rd, dict):
                                    items.extend(rd.get("top_posts", []))
                        except (json.JSONDecodeError, TypeError):
                            pass
        elif isinstance(result, list):
            items = result

        seen = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("link")
            if not url or url in seen:
                continue
            seen.add(url)
            title = (
                item.get("headline")
                or item.get("title")
                or item.get("source")
                or url.split("/")[2]  # domain fallback
            )
            sources.append({"title": title[:80], "url": url})

        return sources

    @staticmethod
    def _append_sources_footer(text: str, sources: list[dict], max_sources: int = 5) -> str:
        """Append a sources section with clickable links if not already present."""
        import html as html_mod
        # Deduplicate by URL, keep first occurrence
        seen = set()
        unique = []
        for s in sources:
            if s["url"] not in seen:
                seen.add(s["url"])
                unique.append(s)
        unique = unique[:max_sources]
        if not unique:
            return text
        lines = ["\n\n\U0001f4ce <b>Sources</b>"]
        for s in unique:
            safe_title = html_mod.escape(s["title"])
            lines.append(f'  <a href="{s["url"]}">{safe_title}</a>')
        return text + "\n".join(lines)

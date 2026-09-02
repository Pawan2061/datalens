"""Create a reader-friendly export containing only questions and final answers."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "exports" / "datalens_conversations_export.json"
JSON_OUTPUT = ROOT / "exports" / "datalens_conversations_reader.json"
MARKDOWN_OUTPUT = ROOT / "exports" / "datalens_conversations_reader.md"


def display_date(value: Any) -> str:
    if not value:
        return "Date not recorded"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.strftime("%d %b %Y, %I:%M %p")
    except ValueError:
        return str(value)


def final_answer(message: dict[str, Any]) -> str:
    insight = message.get("insightResult") or {}
    summary = insight.get("summary") or {}
    answer = (
        summary.get("narrative")
        or message.get("content")
        or message.get("streamingNarrative")
        or ""
    ).strip()
    # Keep the user-facing error message, but omit backend/provider diagnostics
    # that are not useful to a general reader.
    return answer.split("\n\nTechnical detail:", 1)[0].strip()


def build_reader_export(source: dict[str, Any]) -> dict[str, Any]:
    conversations = []
    exchange_count = 0

    sessions = sorted(
        source.get("conversations", []),
        key=lambda item: (item.get("created_at", ""), item.get("id", "")),
    )
    for number, session in enumerate(sessions, start=1):
        messages = session.get("messages") or []
        exchanges = []
        pending_question: dict[str, Any] | None = None

        for message in messages:
            if message.get("role") == "user":
                pending_question = message
                continue
            if message.get("role") != "assistant":
                continue

            question = (pending_question or {}).get("content", "").strip()
            answer = final_answer(message)
            summary = (message.get("insightResult") or {}).get("summary") or {}
            exchanges.append(
                {
                    "question": question,
                    "assistant_response": answer
                    or "No final response was recorded for this question.",
                    **({"response_title": summary["title"]} if summary.get("title") else {}),
                }
            )
            exchange_count += 1
            pending_question = None

        conversations.append(
            {
                "conversation_number": number,
                "date": display_date(session.get("created_at")),
                "title": session.get("title") or "Untitled conversation",
                "exchanges": exchanges,
            }
        )

    return {
        "title": "DataLens Conversation History",
        "description": (
            "A reader-friendly history containing only user questions and the final "
            "assistant responses. System details and usage information are omitted."
        ),
        "conversation_count": len(conversations),
        "exchange_count": exchange_count,
        "conversations": conversations,
    }


def markdown_document(reader: dict[str, Any]) -> str:
    lines = [
        "# DataLens Conversation History",
        "",
        "This document contains the user questions and final assistant responses.",
        "",
        f"Total conversations: {reader['conversation_count']}",
        f"Total questions and answers: {reader['exchange_count']}",
        "",
    ]
    for conversation in reader["conversations"]:
        lines.extend(
            [
                f"## Conversation {conversation['conversation_number']}: {conversation['title']}",
                f"Date: {conversation['date']}",
                "",
            ]
        )
        for index, exchange in enumerate(conversation["exchanges"], start=1):
            lines.extend(
                [
                    f"### Question {index}",
                    "",
                    f"**User:** {exchange['question']}",
                    "",
                    "**Assistant:**",
                    "",
                    exchange["assistant_response"],
                    "",
                ]
            )
    return "\n".join(lines)


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    reader = build_reader_export(source)
    JSON_OUTPUT.write_text(
        json.dumps(reader, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    MARKDOWN_OUTPUT.write_text(markdown_document(reader), encoding="utf-8")
    print(
        json.dumps(
            {
                "json_output": str(JSON_OUTPUT),
                "markdown_output": str(MARKDOWN_OUTPUT),
                "conversation_count": reader["conversation_count"],
                "exchange_count": reader["exchange_count"],
                "json_bytes": JSON_OUTPUT.stat().st_size,
                "markdown_bytes": MARKDOWN_OUTPUT.stat().st_size,
            }
        )
    )


if __name__ == "__main__":
    main()

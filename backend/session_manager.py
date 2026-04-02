"""
Session Manager - In-memory session and message storage
Maintains chat history, tool execution traces, and session state
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from backend.models import ChatMessage, ToolCall

logger_internal = logging.getLogger("mcp_client.internal")


@dataclass
class SimpleSession:
    """Lightweight session data structure"""
    session_id: str
    created_at: datetime = field(default_factory=datetime.now)
    title: str = "New Conversation"
    config: Dict[str, Any] = field(default_factory=dict)
    user_id: Optional[str] = None  # SSO: owning user (None = unauthenticated / legacy)


class SessionManager:
    """Manages chat sessions and message history"""
    
    def __init__(self):
        self.sessions: Dict[str, SimpleSession] = {}
        self.messages: Dict[str, List[ChatMessage]] = {}  # session_id -> messages
        self.tool_traces: Dict[str, List[Dict[str, Any]]] = {}  # session_id -> traces
        self.retrieval_traces: Dict[str, List[Dict[str, Any]]] = {}  # session_id -> retrieval diagnostics
        
        logger_internal.info("SessionManager initialized")
    
    def create_session(self, session_id: Optional[str] = None, config: Optional[Dict[str, Any]] = None, user_id: Optional[str] = None) -> SimpleSession:
        """Create new chat session"""
        
        if session_id is None:
            session_id = str(uuid.uuid4())
        
        session = SimpleSession(
            session_id=session_id,
            created_at=datetime.now(),
            title="New Conversation",
            config=config or {},
            user_id=user_id,
        )
        
        self.sessions[session_id] = session
        self.messages[session_id] = []
        self.tool_traces[session_id] = []
        self.retrieval_traces[session_id] = []
        
        logger_internal.info(f"Created session: {session_id}")
        return session
    
    def get_session(self, session_id: str) -> Optional[SimpleSession]:
        """Get session by ID"""
        return self.sessions.get(session_id)
    
    def list_sessions(self) -> List[SimpleSession]:
        """List all sessions"""
        return list(self.sessions.values())
    
    def delete_session(self, session_id: str) -> bool:
        """Delete session and its data"""
        
        if session_id not in self.sessions:
            return False
        
        del self.sessions[session_id]
        self.messages.pop(session_id, None)
        self.tool_traces.pop(session_id, None)
        self.retrieval_traces.pop(session_id, None)
        
        logger_internal.info(f"Deleted session: {session_id}")
        return True
    
    def add_message(self, session_id: str, message: ChatMessage) -> None:
        """Add message to session history"""
        
        if session_id not in self.messages:
            logger_internal.warning(f"Session {session_id} not found, creating it")
            self.create_session(session_id)
        
        self.messages[session_id].append(message)
        logger_internal.info(f"Added {message.role} message to session {session_id}")
    
    def get_messages(self, session_id: str) -> List[ChatMessage]:
        """Get all messages for a session"""
        return self.messages.get(session_id, [])
    
    def add_tool_trace(
        self,
        session_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Any,
        success: bool
    ) -> None:
        """Add tool execution trace"""
        
        trace = {
            "timestamp": datetime.now().isoformat(),
            "tool_name": tool_name,
            "arguments": arguments,
            "result": result,
            "success": success
        }
        
        if session_id not in self.tool_traces:
            self.tool_traces[session_id] = []
        
        self.tool_traces[session_id].append(trace)
        logger_internal.info(f"Traced tool call: {tool_name} (success={success})")
    
    def get_tool_traces(self, session_id: str) -> List[Dict[str, Any]]:
        """Get tool execution traces for a session"""
        return self.tool_traces.get(session_id, [])

    def add_retrieval_trace(
        self,
        session_id: str,
        *,
        query_hash: str,
        collection_keys: List[str],
        result_count: int,
        degraded: bool,
        degraded_reason: str = "",
        latency_ms: float = 0.0,
    ) -> None:
        """Add retrieval trace for a session."""

        if session_id not in self.retrieval_traces:
            self.retrieval_traces[session_id] = []

        self.retrieval_traces[session_id].append(
            {
                "query_hash": query_hash,
                "collection_keys": list(collection_keys),
                "result_count": result_count,
                "degraded": degraded,
                "degraded_reason": degraded_reason,
                "latency_ms": latency_ms,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def get_retrieval_traces(self, session_id: str) -> List[Dict[str, Any]]:
        """Get retrieval traces for a session."""
        return list(self.retrieval_traces.get(session_id, []))
    
    def update_session_title(self, session_id: str, title: str) -> bool:
        """Update session title"""
        
        if session_id not in self.sessions:
            return False
        
        self.sessions[session_id].title = title
        logger_internal.info(f"Updated session title: {session_id} -> {title}")
        return True
    
    def get_messages_for_llm(self, session_id: str, provider: str = "openai", start_index: int = 0) -> List[Dict[str, Any]]:
        """Convert messages to LLM API format
        
        Args:
            session_id: Session identifier
            provider: LLM provider ('openai' or 'ollama') - affects tool_call_id inclusion
            start_index: Index offset into session messages for scoped history
        """
        
        messages = self.get_messages(session_id)[start_index:]
        
        llm_messages = []
        for msg in messages:
            # Ensure content is always a string (Ollama requires this)
            content = msg.content if msg.content is not None else ""
            
            # For Ollama, convert tool messages to user messages with tool result prefix
            # This avoids JSON parsing issues with tool role
            if provider == "ollama" and msg.role == "tool":
                llm_messages.append({
                    "role": "user",
                    "content": f"Tool result: {content}"
                })
                continue
            
            msg_dict = {
                "role": msg.role,
                "content": content
            }
            
            # Add tool calls if present (for assistant messages)
            if msg.tool_calls:
                # For Ollama, tool_calls in history cause parsing errors.
                if provider == "ollama":
                    if not content:
                        # Emit a brief synthetic assistant turn so the following
                        # tool-result user message doesn't land as a consecutive
                        # user message, which breaks conversation alternation and
                        # causes Ollama models to stop calling tools on later turns.
                        llm_messages.append({"role": "assistant", "content": "Let me check that using available tools."})
                        continue
                    # Otherwise just use the content without tool_calls
                else:
                    # OpenAI format - include tool_calls
                    msg_dict["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments if isinstance(tc.function.arguments, str) else "{}"
                            }
                        }
                        for tc in msg.tool_calls
                    ]
            
            # Add tool_call_id for OpenAI-compatible providers (not Ollama)
            # Enterprise gateway is OpenAI-compatible and also requires tool_call_id
            if provider != "ollama" and hasattr(msg, 'tool_call_id') and msg.tool_call_id:
                msg_dict["tool_call_id"] = msg.tool_call_id
            
            llm_messages.append(msg_dict)
        
        return llm_messages

    def build_history_summary(
        self,
        session_id: str,
        *,
        upto_index: Optional[int] = None,
        max_messages: int = 6,
        max_traces: int = 4,
    ) -> Optional[str]:
        """Build a compact summary of recent session context for LLM prompts."""

        messages = self.get_messages(session_id)
        if upto_index is not None:
            messages = messages[:upto_index]

        if not messages:
            return None

        recent_messages = messages[-max_messages:]
        recent_user_requests = [
            (msg.content or "").strip()
            for msg in recent_messages
            if msg.role == "user" and (msg.content or "").strip()
        ]
        recent_assistant_answers = [
            (msg.content or "").strip()
            for msg in recent_messages
            if msg.role == "assistant" and (msg.content or "").strip()
        ]

        traces = self.get_tool_traces(session_id)
        if upto_index is not None and upto_index < len(self.get_messages(session_id)):
            tool_messages_before_index = sum(1 for msg in self.get_messages(session_id)[:upto_index] if msg.role == "tool")
            traces = traces[:tool_messages_before_index]
        recent_traces = traces[-max_traces:]
        recent_retrieval_traces = self.get_retrieval_traces(session_id)[-max_traces:]

        summary_parts: List[str] = []
        if recent_user_requests:
            summary_parts.append(
                "Recent user requests: " + " | ".join(recent_user_requests[-3:])
            )
        if recent_assistant_answers:
            summary_parts.append(
                "Recent assistant findings: " + " | ".join(recent_assistant_answers[-2:])
            )
        if recent_traces:
            rendered_traces = []
            for trace in recent_traces:
                tool_name = trace.get("tool_name", "unknown")
                status = "success" if trace.get("success") else "failed"
                result = trace.get("result")
                result_preview = str(result)
                result_preview = " ".join(result_preview.split())[:120]
                rendered_traces.append(f"{tool_name} ({status}): {result_preview}")
            summary_parts.append("Recent tool outcomes: " + " | ".join(rendered_traces))
        if recent_retrieval_traces:
            degraded_count = sum(1 for trace in recent_retrieval_traces if trace.get("degraded"))
            summary_parts.append(
                f"Recent retrieval activity: {len(recent_retrieval_traces)} event(s), {degraded_count} degraded"
            )

        if not summary_parts:
            return None

        return "\n".join(summary_parts)

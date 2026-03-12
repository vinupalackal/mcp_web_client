"""
Session Manager - In-memory session and message storage
Maintains chat history, tool execution traces, and session state
"""

import logging
import uuid
from datetime import datetime
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


class SessionManager:
    """Manages chat sessions and message history"""
    
    def __init__(self):
        self.sessions: Dict[str, SimpleSession] = {}
        self.messages: Dict[str, List[ChatMessage]] = {}  # session_id -> messages
        self.tool_traces: Dict[str, List[Dict[str, Any]]] = {}  # session_id -> traces
        
        logger_internal.info("SessionManager initialized")
    
    def create_session(self, session_id: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> SimpleSession:
        """Create new chat session"""
        
        if session_id is None:
            session_id = str(uuid.uuid4())
        
        session = SimpleSession(
            session_id=session_id,
            created_at=datetime.now(),
            title="New Conversation",
            config=config or {}
        )
        
        self.sessions[session_id] = session
        self.messages[session_id] = []
        self.tool_traces[session_id] = []
        
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
                # For Ollama, skip tool_calls in history - it causes parsing errors
                # Just keep the content if any
                if provider == "ollama":
                    # Skip this message entirely if it has no content
                    if not content:
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

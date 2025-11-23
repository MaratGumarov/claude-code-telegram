# Claude Code Streaming API Research Notes

**Date:** 2025-11-21
**Context:** Research into Claude Code streaming JSON API for building a Telegram bot integration

---

## 🎯 Project Goal

Build a Telegram bot that provides full interactive access to Claude Code with:
- Real-time notifications when tasks complete or user attention needed
- Ability to respond to Claude Code prompts from mobile device
- Support for permission requests and interactive sessions
- Persistent multi-turn conversations

---

## 🔔 Part 1: Sound Notifications Setup

### Audio Notifications via Hooks

Configured Claude Code hooks in `~/.claude/settings.json` to play sounds on events:

```json
{
  "hooks": {
    "SubagentStop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "say 'Задача завершена'"
          }
        ]
      }
    ],
    "PermissionRequest": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "say 'Требуется ваше внимание'"
          }
        ]
      }
    ]
  }
}
```

**Available Hook Events:**
- `SubagentStop` - Task/subagent completion
- `PermissionRequest` - Permission dialogs
- `Notification` - General alerts
- `Stop` - Main agent finishes
- `PostToolUse` - After tool execution
- `PreToolUse` - Before tool execution
- `SessionStart` - Session initialization
- `SessionEnd` - Session termination

**macOS TTS:**
- Built-in `say` command with Siri Voice 2
- Alternative: `afplay /System/Library/Sounds/Glass.aiff` for sound effects

---

## 🌐 Part 2: Remote Control Investigation

### Initial Options Explored

1. **SSH + Tmux** ✅ - Full interactivity, requires SSH access
2. **Telegram Bot** 🎯 - Mobile-friendly, push notifications
3. **GitHub Actions** - Comment-based triggers
4. **Headless Mode** - Programmatic access

### Key Discovery: Streaming JSON API

Claude Code supports **streaming JSON mode** for programmatic interaction:

```bash
claude --print \
  --input-format stream-json \
  --output-format stream-json \
  --verbose
```

---

## 🔍 Part 3: Streaming JSON Format

### Input Message Format

**Correct format** (JSONL - JSON Lines):
```json
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"Your message here"}]}}
```

**Key structure:**
- `type`: "user" (required)
- `message.role`: "user" (required)
- `message.content`: **array of content blocks** (not a string!)
- Content blocks have `type` and corresponding data (e.g., `type: "text"` with `text: "..."`)

**Common Mistakes:**
```json
// ❌ Wrong: content as string
{"type":"user","content":"message"}

// ❌ Wrong: missing message wrapper
{"type":"user","role":"user","content":"message"}

// ✅ Correct: content as array of objects
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"message"}]}}
```

### Output Event Types

Claude Code streams these event types:

1. **`system`** - Initialization with session_id, tools list, MCP servers
2. **`assistant`** - Claude's responses and tool_use requests
3. **`user`** - Tool results from system (including permission denials)
4. **`result`** - Final result with cost, tokens, and metrics

**Example Output:**
```json
{"type":"system","subtype":"init","session_id":"...","tools":[...],"model":"claude-sonnet-4-5-20250929"}
{"type":"assistant","message":{"content":[{"type":"text","text":"Response"}],"stop_reason":"end_turn"}}
{"type":"result","subtype":"success","result":"Response text","total_cost_usd":0.05}
```

---

## 🔐 Part 4: Permission Requests Deep Dive

### How Permission Requests Work

**NO separate `permission_request` event exists!** Permissions are handled through the normal tool flow:

1. Claude sends `assistant` message with `tool_use`:
   ```json
   {"type":"assistant","message":{"content":[
     {"type":"tool_use","id":"toolu_xxx","name":"Write","input":{"file_path":"...","content":"..."}}
   ]}}
   ```

2. System responds with `user` message containing `tool_result`:
   ```json
   {"type":"user","message":{"role":"user","content":[{
     "type":"tool_result",
     "content":"Claude requested permissions to write to ..., but you haven't granted it yet.",
     "is_error":true,
     "tool_use_id":"toolu_xxx"
   }]}}
   ```

3. Without response, Claude times out or ends the conversation

### Permission Modes - The Solution! 🎉

Instead of programmatically approving permissions (not currently supported), use **permission modes**:

| Flag | Behavior | Use Case |
|------|----------|----------|
| `--permission-mode acceptEdits` | Auto-approve Write, Edit, Read | ✅ Safe for file operations |
| `--permission-mode bypassPermissions` | Skip all permission checks | ⚠️ Use with caution |
| `--dangerously-skip-permissions` | Bypass everything | ⚠️ Very dangerous |
| `--permission-mode default` | Interactive prompts | 🔐 Manual approval |

**Test Results:**
```bash
# ❌ Without permission mode - times out waiting for approval
echo '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"Создай файл test.txt"}]}}' \
  | claude --print --input-format stream-json --output-format stream-json
# Result: "Request timed out"

# ✅ With acceptEdits - works automatically
echo '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"Создай файл test.txt"}]}}' \
  | claude --print --input-format stream-json --output-format stream-json --permission-mode acceptEdits
# Result: File created successfully!
```

---

## 📊 Part 5: Multi-Turn Conversations

**JSONL Format** for multiple messages:
```jsonl
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"Сколько будет 2+2?"}]}}
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"А 3+3?"}]}}
```

**Each line is processed as a separate turn**, maintaining conversation context.

### Session Management

- `--session-id <uuid>` - Use specific session ID
- `--continue` - Continue most recent conversation
- `--resume [sessionId]` - Resume specific session
- `--fork-session` - Create new session from resumed one

---

## 🤖 Part 6: Existing Solution Analysis

### claude-code-telegram Repository

**URL:** https://github.com/RichardAtCT/claude-code-telegram
**Stars:** 120 ⭐
**Status:** Active development

#### Architecture

```
Telegram User → Telegram Bot → Claude Code (SDK/CLI)
                     ↓
              Session Manager (SQLite)
              Security Layer (whitelist, sandboxing)
```

#### Key Dependencies

```toml
python-telegram-bot = "^22.1"
anthropic = "^0.40.0"
claude-code-sdk = "^0.0.11"  # 🔑 SDK for programmatic access
aiosqlite = "^0.21.0"
pydantic = "^2.11.5"
```

#### Features

✅ **Working:**
- Full Telegram bot integration
- Session persistence (SQLite)
- Multi-user support with whitelist
- Directory sandboxing for security
- Cost tracking per user
- Quick action buttons
- Git integration
- File/image upload
- Archive analysis

⚠️ **Planned:**
- True streaming responses (currently buffered)
- Claude vision API full integration
- Custom quick actions
- Plugin system

#### Security Model

- User ID whitelist (`ALLOWED_USERS`)
- Directory restriction (`APPROVED_DIRECTORY`)
- Rate limiting (token bucket)
- Audit logging
- Cost limits per user

---

## 💡 Recommendations

### Strategy: Start with Existing Solution

**Phase 1: Use claude-code-telegram** ✅
- Production-ready code
- Security built-in
- Session management
- Cost tracking

**Phase 2: Contribute Improvements** 🚀
- Add true streaming using our research
- Implement real-time permission approvals
- Custom features as needed

### Streaming Implementation Plan

If adding streaming to claude-code-telegram:

1. **Replace buffered responses** with streaming JSON API:
   ```python
   process = subprocess.Popen([
       'claude', '--print',
       '--input-format', 'stream-json',
       '--output-format', 'stream-json',
       '--permission-mode', 'acceptEdits'
   ], stdin=PIPE, stdout=PIPE, stderr=PIPE)
   ```

2. **Parse JSONL output** line by line:
   ```python
   for line in iter(process.stdout.readline, b''):
       event = json.loads(line)
       if event['type'] == 'assistant':
           # Send to Telegram immediately
           await telegram_bot.send_message(event['message']['content'])
   ```

3. **Handle permission strategy:**
   - Safe tools (Write, Edit, Read) → `acceptEdits`
   - Dangerous tools (Bash) → Ask user via Telegram buttons → Use `bypassPermissions` if approved

---

## 🔧 Technical Details

### Claude Code CLI Flags Summary

```bash
# Streaming JSON
--input-format stream-json      # Accept JSONL input
--output-format stream-json     # Output JSONL events
--verbose                        # Required with stream-json output

# Permission Control
--permission-mode acceptEdits    # Auto-approve file edits
--dangerously-skip-permissions   # Skip all permissions

# Session Management
--session-id <uuid>              # Use specific session
--continue                       # Continue last session
--resume [id]                    # Resume specific session

# Tool Control
--tools <list>                   # Specify available tools
--allowedTools <tools>           # Whitelist specific tools
--disallowedTools <tools>        # Blacklist specific tools

# Model Selection
--model <model>                  # Specify model (sonnet, opus, haiku)
--fallback-model <model>         # Fallback when overloaded
```

### Permission Modes Comparison

| Mode | Write | Edit | Read | Bash | MCP Tools |
|------|-------|------|------|------|-----------|
| `default` | ❓ Ask | ❓ Ask | ❓ Ask | ❓ Ask | ❓ Ask |
| `acceptEdits` | ✅ Auto | ✅ Auto | ✅ Auto | ❓ Ask | ❓ Ask |
| `bypassPermissions` | ✅ Auto | ✅ Auto | ✅ Auto | ✅ Auto | ✅ Auto |

---

## 📝 Working Examples

### Simple Request
```bash
echo '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"Привет! Ответь одним словом"}]}}' \
  | claude --print --verbose \
    --input-format stream-json \
    --output-format stream-json \
    --tools ""
```

### File Creation with Auto-Approval
```bash
echo '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"Создай файл test.txt с текстом Hello"}]}}' \
  | claude --print --verbose \
    --input-format stream-json \
    --output-format stream-json \
    --permission-mode acceptEdits
```

### Multi-Turn Conversation
```bash
cat <<'EOF' | claude --print --verbose --input-format stream-json --output-format stream-json --tools ""
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"Сколько будет 2+2?"}]}}
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"А 3+3?"}]}}
EOF
```

---

## 🎯 Next Steps

1. **Install claude-code-telegram:**
   ```bash
   cd ~/Projects/claude-code-telegram
   poetry install
   cp .env.example .env
   # Edit .env with Telegram token and settings
   make run
   ```

2. **Test basic functionality:**
   - Create Telegram bot via @BotFather
   - Get user ID from @userinfobot
   - Configure ALLOWED_USERS
   - Test interactive session

3. **Evaluate performance:**
   - Check response latency
   - Test permission handling
   - Verify session persistence

4. **Plan improvements if needed:**
   - Fork repository
   - Implement streaming
   - Add permission approval flow
   - Submit PR

---

## 📚 References

- [Claude Code Documentation](https://code.claude.com/docs)
- [claude-code-telegram GitHub](https://github.com/RichardAtCT/claude-code-telegram)
- [Anthropic Claude API](https://docs.anthropic.com/)
- [python-telegram-bot](https://python-telegram-bot.org/)

---

## 🤝 Contributors

Research and documentation by Claude Code session on 2025-11-21.

---

## 📌 Key Takeaways

1. ✅ Claude Code has a **streaming JSON API** for programmatic access
2. ✅ Permission requests are **tool_result events**, not separate messages
3. ✅ **Permission modes** solve auto-approval (`--permission-mode acceptEdits`)
4. ✅ **claude-code-telegram** is production-ready with solid architecture
5. ✅ Streaming can be added as contribution using our research
6. ✅ **Sound notifications** work via hooks with macOS `say` command

**Decision:** Use existing claude-code-telegram project, contribute streaming if needed.
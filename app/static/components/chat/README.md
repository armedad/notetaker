# ChatUI Component

A self-contained, streaming chat component. Renders a chat interface with message bubbles, text input, and optional search. Streams responses from a server endpoint via Server-Sent Events (SSE) and optionally persists history to a REST API.

No build step required — works as a plain `<script>` tag.

## Quick start

```html
<link rel="stylesheet" href="components/chat/chat-ui.css" />
<script src="components/chat/chat-ui.js"></script>

<div id="my-chat"></div>

<script>
  const chat = new ChatUI({
    container: document.getElementById('my-chat'),
    endpoint: '/api/chat',
  });
</script>
```

## Constructor options

| Option | Type | Default | Description |
|---|---|---|---|
| `container` | `HTMLElement` | *required* | DOM element to render the chat into. |
| `endpoint` | `string` | *required* | URL for POST requests. Must return an SSE stream (see protocol below). |
| `buildPayload` | `Function` | `(q) => ({ question: q })` | Transforms the user's question into a JSON request body. |
| `placeholder` | `string` | `"Ask a question..."` | Input field placeholder text. |
| `title` | `string` | `"Chat"` | Header title (standard variant only). |
| `emptyText` | `string` | `"Ask a question..."` | Text shown when the message list is empty. |
| `fullscreen` | `boolean` | `false` | Use the fullscreen layout variant. |
| `minimal` | `boolean` | `false` | Use the minimal layout variant. |
| `enableSearch` | `boolean` | `true` | Set `false` to hide search UI entirely. |
| `searchPlaceholder` | `string` | `"Search..."` | Placeholder for the search input. |
| `roleLabels` | `object` | `{ user: "You", assistant: "Assistant" }` | Display labels for message roles. |
| `statusMessages` | `object` | `{ sending: "Sending...", generating: "Generating response...", cancelled: "Cancelled" }` | Text shown at each stage. |
| `historyEndpoint` | `string\|null` | `null` | URL for GET/PUT history persistence. `null` disables persistence. |
| `searchContainer` | `HTMLElement\|null` | `null` | External DOM element containing `.chat-search-bar` markup (for embedding search in a panel header). |
| `searchToggle` | `HTMLElement\|null` | `null` | External button that toggles search visibility. |
| `onSendMessage` | `Function\|null` | `null` | Hook called with `(payload)` before fetch — lets you mutate the payload. |

## Public API

### Messaging

| Method | Signature | Description |
|---|---|---|
| `sendMessage()` | `async sendMessage()` | Reads the input, posts to the endpoint, and streams the response. |
| `addMessage(role, content, streaming?, timestamp?)` | `addMessage(role, content, streaming=false, timestamp=null)` | Adds a message bubble. Returns the DOM element when `streaming=true`. |
| `clearMessages()` | `clearMessages()` | Clears all messages and persists the empty state. |
| `cancel()` | `cancel()` | Aborts the current in-flight request. |

### UI state

| Method | Description |
|---|---|
| `setLoading(loading)` | Toggle input/button disabled state and loading indicator. |
| `setStatus(message)` | Show a temporary status bubble in the messages area. Pass `""` to hide. |
| `scrollToBottom()` | Scroll the messages container to the bottom. |
| `toggleCollapse()` | Toggle body visibility (standard variant only). |

### Search

| Method | Description |
|---|---|
| `openSearch()` | Show the search bar and focus the input. |
| `closeSearch()` | Hide the search bar and clear highlights. |
| `performSearch(query)` | Case-insensitive full-text search with `<mark>` highlights. |
| `navigateSearch(direction)` | `+1` for next match, `-1` for previous. Wraps around. |

### Persistence

| Method | Description |
|---|---|
| `loadHistory()` | Fetch and render saved messages from `historyEndpoint`. |
| `saveHistory()` | PUT current messages to `historyEndpoint`. |

### Lifecycle

| Method | Description |
|---|---|
| `destroy()` | Cancel pending requests and remove all rendered DOM. |

## SSE protocol

The `endpoint` must accept a `POST` with `Content-Type: application/json` and return a streaming response with `text/event-stream` content type.

### Token stream

```
data: {"token": "Hello"}

data: {"token": " world"}

data: [DONE]
```

- `data: {"token": "..."}` — a text chunk to append to the assistant's message.
- `data: [DONE]` — literal string (not JSON). Signals the end of the stream.
- `data: {"error": "..."}` — an error message rendered in the chat.

### Non-200 responses

If the HTTP response is not 200, ChatUI tries to parse the body as JSON and looks for `detail`, `error`, or `message` fields. Falls back to raw text.

## History API

When `historyEndpoint` is set:

**Load** — called once on construction:

```
GET {historyEndpoint}
→ { "messages": [{ "role": "user", "content": "...", "timestamp": "..." }, ...] }
```

**Save** — called after each `sendMessage()` completes and after `clearMessages()`:

```
PUT {historyEndpoint}
Content-Type: application/json
{ "messages": [{ "role": "user", "content": "...", "timestamp": "..." }, ...] }
```

The `timestamp` field is an ISO 8601 string. It's optional on load (defaults to the current time).

## CSS theming

The component CSS uses CSS custom properties. Your app must define these (or provide defaults):

### Required variables

| Variable | Used for |
|---|---|
| `--bg-panel` | Panel background, assistant message background |
| `--bg-secondary` | Header, messages area, search bar, input area backgrounds |
| `--bg-hover` | Search button hover state |
| `--bg-input` | Input field background |
| `--bg-input-disabled` | Disabled input field background |
| `--bg-user-message` | User message bubble background |
| `--text-primary` | Input text color |
| `--text-secondary` | Title color |
| `--text-muted` | Role labels, status text, search count |
| `--text-placeholder` | Empty state, timestamp text |
| `--border-default` | Panel borders, message borders |
| `--border-input` | Input field border |
| `--border-focus` | Focused input border |
| `--accent-primary` | Send button background |
| `--accent-primary-hover` | Send button hover background |
| `--shadow-md` | Panel box shadow |
| `--color-warning-bg` | Search match highlight |
| `--color-warning` | Current search match highlight |

## Layout variants

### Fullscreen (`fullscreen: true`)

No header. Fills the container height. Messages are centered with max-width constraints. The search toggle sits in a thin top bar. Best for a primary chat view.

### Minimal (`minimal: true`)

No header, no clear/collapse buttons. Designed for embedding in a panel. Search UI must be provided externally via `searchContainer` and `searchToggle`.

### Standard (default)

Collapsible header with title, search toggle, clear, and collapse buttons. A standalone search bar appears below the header. Good for secondary or embedded chat.

## External search

For embedding the search bar in an external header (e.g. a panel title bar):

1. Add the search markup to your header:

```html
<div id="my-search-bar" class="chat-search-bar chat-search-bar-inline" style="display:none">
  <input class="chat-search-input" placeholder="Search..." />
  <span class="chat-search-count">0/0</span>
  <button class="chat-search-prev" title="Previous">&#9650;</button>
  <button class="chat-search-next" title="Next">&#9660;</button>
</div>
<button id="my-search-toggle" class="icon-btn" title="Search">&#128269;</button>
```

2. Pass the elements to ChatUI:

```js
new ChatUI({
  container: document.getElementById('chat'),
  endpoint: '/api/chat',
  minimal: true,
  searchContainer: document.getElementById('my-search-bar').parentElement,
  searchToggle: document.getElementById('my-search-toggle'),
});
```

ChatUI will wire up all event listeners on the external elements and manage show/hide automatically.

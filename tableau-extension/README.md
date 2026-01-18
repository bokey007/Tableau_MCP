# Tableau Extension: AI Analytics Agent

A Tableau Dashboard Extension that provides an AI-powered natural language interface for data analysis, embedded directly in your Tableau dashboards.

## ✨ Features

- **Natural Language Queries**: Ask questions in plain English
- **Dashboard Context Awareness**: Uses current filters, selections, and parameters
- **Context Scope Detection**: Intelligently detects filtered vs global queries
- **Markdown Rendering**: Rich formatted responses with tables and code blocks
- **Chart Visualizations**: Chart.js powered visualizations
- **Conversation Memory**: Multi-turn conversations with follow-up support
- **Dark Theme UI**: Modern aesthetic matching Tableau

## 📁 Project Structure

```
tableau-extension/
├── ai-analytics-agent.trex    # Extension manifest (register with Tableau)
├── icons/                     # Extension icons
├── src/
│   ├── index.html             # Main extension UI
│   ├── app.js                 # Application logic (Chart.js, marked.js)
│   ├── styles.css             # Dark theme styling
│   └── demo.html              # Standalone demo (no Tableau required)
└── README.md
```

## 🚀 Quick Start (Demo Mode)

Test the extension without Tableau:

```bash
cd src
python3 -m http.server 8080
# Open http://localhost:8080/demo.html
```

This uses a simulated dashboard context with filters for testing.

## 🔌 Deployment

### Prerequisites

1. **Backend API**: The Tableau MCP Agent backend must be deployed
2. **HTTPS**: Extension files must be served over HTTPS
3. **Tableau Cloud/Server**: Admin access to allow-list extension

### Step 1: Configure API URL

Edit `src/app.js`:

```javascript
const CONFIG = {
  API_URL: "https://your-backend-url.com/api/v1",
  TIMEOUT: 120000,
  DEBUG: false,
};
```

### Step 2: Update Manifest

Edit `ai-analytics-agent.trex`:

```xml
<source-location>
    <url>https://your-extension-host.com/index.html</url>
</source-location>
```

### Step 3: Deploy Extension Files

Host `src/` contents on HTTPS-enabled web server:

```bash
# Files needed:
# - index.html
# - app.js
# - styles.css
```

### Step 4: Configure CORS

Add your Tableau domain to backend's `CORS_ORIGINS`:

```
CORS_ORIGINS=https://your-tableau-site.tableau.com
```

### Step 5: Allow-list in Tableau

1. Log in to Tableau Cloud as Site Admin
2. Go to **Settings** → **Extensions**
3. Under "Enable Specific Extensions", add extension URL
4. Save changes

### Step 6: Add to Dashboard

1. Open Tableau dashboard in edit mode
2. Drag **Extension** object onto dashboard
3. Click "Add from file" → select `.trex` file
4. Extension loads and connects to backend

## 🧠 Intent Classification

| Intent              | Examples                    | Behavior               |
| ------------------- | --------------------------- | ---------------------- |
| `chat`              | "Hello", "Thanks"           | Friendly response      |
| `capability`        | "What can you do?"          | Lists capabilities     |
| `dashboard_context` | "What filters are applied?" | Shows current context  |
| `clarification`     | "sales" (vague)             | Asks for clarification |
| `data_query`        | "Top 5 products by sales"   | Executes VizQL query   |

## 🔍 Context Scope Detection

| User Question        | Scope    | Behavior               |
| -------------------- | -------- | ---------------------- |
| "Top 5 products"     | Filtered | Uses dashboard filters |
| "Show all regions"   | Global   | Ignores filters        |
| "In this view"       | Filtered | Uses current filters   |
| "Company-wide total" | Global   | Queries all data       |

## 🎨 UI Components

| Component | Library     | Purpose               |
| --------- | ----------- | --------------------- |
| Markdown  | marked.js   | Render formatted text |
| Charts    | Chart.js    | Render visualizations |
| Tables    | Native HTML | Data preview          |

## 🔧 Configuration

| Setting   | Description          | Default                        |
| --------- | -------------------- | ------------------------------ |
| `API_URL` | Backend API endpoint | `http://localhost:8000/api/v1` |
| `TIMEOUT` | Request timeout (ms) | `120000`                       |
| `DEBUG`   | Console logging      | `true`                         |

## 🐛 Troubleshooting

| Issue                   | Solution                               |
| ----------------------- | -------------------------------------- |
| "Extension not allowed" | Add URL to Tableau allow-list          |
| CORS errors             | Add extension domain to `CORS_ORIGINS` |
| "Connection error"      | Check backend is running               |
| No charts               | Ensure Chart.js CDN loads              |
| No markdown             | Ensure marked.js CDN loads             |

## 🔒 Security

- CORS configured for specific origins
- Uses Tableau's authentication context
- No sensitive data stored in browser
- PHI sanitized before logging

## 📝 License

MIT License - Part of the Tableau MCP AI Agent project.

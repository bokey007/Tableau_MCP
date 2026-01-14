# Tableau Extension: AI Analytics Agent

A Tableau Dashboard Extension that provides an AI-powered natural language interface for data analysis.

## 📁 Project Structure

```
tableau-extension/
├── ai-analytics-agent.trex    # Extension manifest (register with Tableau)
├── src/
│   ├── index.html             # Main extension UI
│   ├── styles.css             # Styling
│   └── app.js                 # Application logic
└── README.md                  # This file
```

## 🚀 Deployment

### Prerequisites

1. **Backend API**: The main Tableau MCP Agent must be deployed and accessible
2. **HTTPS**: Extension must be served over HTTPS (required by Tableau)
3. **Tableau Cloud Access**: Site Admin access to allow-list the extension

### Step 1: Update Configuration

Edit `src/app.js` and update the `CONFIG` object:

```javascript
const CONFIG = {
  API_URL: "https://your-ares-domain.company.com/api/v1",
  TIMEOUT: 120000,
  DEBUG: false, // Set to false in production
};
```

### Step 2: Update Manifest

Edit `ai-analytics-agent.trex` and update the source URL:

```xml
<source-location>
    <url>https://your-ares-domain.company.com/extension/index.html</url>
</source-location>
```

### Step 3: Deploy Extension Files

Deploy the `src/` folder contents to a web server accessible via HTTPS:

```bash
# Example: Copy to ARES static hosting
scp -r src/* user@ares-server:/var/www/extension/
```

### Step 4: Allow-list in Tableau Cloud

1. Log in to Tableau Cloud as Site Admin
2. Go to **Settings** → **Extensions**
3. Under "Enable Specific Extensions", add:
   ```
   https://your-ares-domain.company.com/extension/
   ```
4. Save changes

### Step 5: Add to Dashboard

1. Open a Tableau dashboard in edit mode
2. Drag an **Extension** object onto the dashboard
3. Click "Access Local Extensions"
4. Upload `ai-analytics-agent.trex`
5. The extension will load and connect to your backend

## 🧪 Local Development

For local testing without HTTPS:

1. Start a local web server:

   ```bash
   cd src
   python -m http.server 8080
   ```

2. Update the manifest to use localhost:

   ```xml
   <url>http://localhost:8080/index.html</url>
   ```

3. In Tableau Desktop, enable unsigned extensions:

   - Help → Settings and Performance → Enable Debugging

4. Load the extension from the local `.trex` file

## 🔧 Configuration Options

| Setting   | Description            | Default                        |
| --------- | ---------------------- | ------------------------------ |
| `API_URL` | Backend API endpoint   | `http://localhost:8000/api/v1` |
| `TIMEOUT` | Request timeout (ms)   | `120000`                       |
| `DEBUG`   | Enable console logging | `true`                         |

## 📊 Features

- **Natural Language Queries**: Ask questions in plain English
- **Dashboard Context**: Automatically captures current filters and datasources
- **Data Preview**: Shows tabular data preview in chat
- **Visualization Recommendations**: Suggests appropriate chart types
- **Dark Theme**: Matches Tableau's modern aesthetic

## 🔒 Security Notes

1. **CORS**: Backend must allow requests from your extension domain
2. **Authentication**: Uses Tableau's built-in authentication context
3. **PHI Handling**: Queries containing PHI are sanitized before logging

## 🐛 Troubleshooting

| Issue                         | Solution                                     |
| ----------------------------- | -------------------------------------------- |
| "Extension not allowed"       | Ensure URL is in Tableau allow-list          |
| "Connection error"            | Check if backend API is accessible           |
| CORS errors                   | Add extension domain to backend CORS_ORIGINS |
| "Tableau API not initialized" | Ensure running inside Tableau dashboard      |

## 📝 License

Internal use only. Part of the GenAI Tableau MCP project.

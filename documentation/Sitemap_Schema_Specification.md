# Sitemap JSON Schema & Integration Specification

This document defines the schema, structure, configuration keys, and generation requirements for the Sitemap JSON files used by the **Automated Sitemap Accessibility Control Center (ASACC)**.

---

## 1. Overview of Sitemap JSON

The sitemap JSON file acts as:
1. **State Persistence**: Saves GUI configurations (credentials, selected tasks, target URL, and execution options) bound to each specific network target.
2. **Visual Mapping Tree**: Populates the Tkinter `Treeview` visualization in the control panel.
3. **Audit Checkpoint**: Stores crawl state (`initialized`), page metadata (titles, depths), and accessibility verification timestamps (`verified_at` for static audits, `dynamic_verified_at` for dynamic audits).

---

## 2. Prerequisites to Generate a Map

To build a sitemap file, the crawler requires:
1. **Target URL**: The base URL of the Web application (e.g., `http://localhost:8000`).
2. **Authentication Credentials** (Optional): A default username and password to log past authentication portals using the AI Pre-login engine.
3. **Seed Node**: A minimal skeleton file containing at least the root node `"/"` as a starting point.
   - If no file exists, the system automatically initializes a minimal template containing `"/"` when starting a scan.

---

## 3. JSON Field Definitions

A sitemap JSON is divided into two parts: **Top-level UI settings** and the **`nodes` dictionary**.

### A. Top-Level UI Settings (GUI Configuration Persistence)
These parameters are automatically loaded into the GUI widgets on sitemap selection, and serialized back to the JSON file on audit execution.

| Key | Type | Description |
| :--- | :--- | :--- |
| `target_url` | String | The absolute URL of the web server (e.g., `"http://192.168.1.1"`). |
| `default_username` | String | Default username to auto-fill in credentials. |
| `default_password` | String | Default password to auto-fill in credentials. |
| `main_task` | String | Currently active task dropdown selection (e.g., `"探索與初始化網站地圖 (Explore & Initialize Sitemap)"`, `"動態單頁無障礙檢測"`). |
| `page_path` | String | Specific target page path (used primarily for single-page dynamic audits, e.g., `"/overview"`). |
| `wcag_sel` | String | Selected WCAG chapter guideline (e.g., `"ALL"`, `"DYNAMIC_ALL"`, `"2.1"`). |
| `use_custom_model` | Boolean | Whether to override the default model with a custom model name string. |
| `custom_model` | String | Overriding model string (e.g., `"claude-3-5-sonnet-20241022"`). |
| `model` | String | Default model string select dropdown option. |
| `device` | String | Viewport simulation mode (`"desktop"` or `"mobile"`). |
| `max_turns` | Integer | Max execution turns for AI agent interactions. |
| `headless` | Boolean | Whether Playwright runs headless or headful (visible browser). |
| `record` | Boolean | Whether to record WebP session videos in the artifacts folder. |
| `total_pages` | Integer | Total number of nodes (including actual pages and virtual category folders). |
| `last_verified` | String | Last global update timestamp (`YYYY-MM-DD HH:MM:SS`). |

---

### B. The `nodes` Properties
The `nodes` object contains a mapping where key is the page path (`/path/to/page`) and value is the node object.

| Node Property | Type | Description |
| :--- | :--- | :--- |
| `path` | String | The path relative to `target_url` (e.g. `"/advanced/network/lan"`). |
| `title` | String | Page title retrieved from `<title>` tags or designated name. |
| `parent` | String or Null | Relative path of the parent node in the URL directory hierarchy. |
| `children` | Array of Strings | List of relative paths of direct child nodes. |
| `is_leaf` | Boolean | `true` if this node has no children; `false` otherwise. |
| `depth` | Integer | Depth level in the tree directory hierarchy (calculated by splitting `/`). `/` has depth `0`. |
| `status` | String | State tag: `"UNVERIFIED"`, `"OK"`, `"CATEGORY"`, or `"ERROR"`. |
| `error` | Boolean or String | `false` if healthy, or error details if connection failed. |
| `initialized` | Boolean | `true` if the crawler successfully navigated to the page; `false` otherwise. |
| `initialized_at`| String | Crawl timestamp (`YYYY-MM-DD HH:MM:SS`). |
| `verified_at` | String (Opt) | Timestamp of last static Axe-core accessibility audit. |
| `dynamic_verified_at` | String (Opt) | Timestamp of last dynamic AI-based keyboard/focus audit. |

---

## 4. Special Node Status Behavior: `CATEGORY` (Virtual Folder Nodes)

To keep the treeview structure deeply branched and structured:
* **The Problem**: A flat list of pages discovered under `/advanced` (e.g., `/advanced/network/lan/ip`) has no intermediate pages (e.g., `/advanced/network` or `/advanced/network/lan` are not links, but headings).
* **The Solution**: The sitemap hierarchy engine automatically generates **Virtual Folders** (marked as `"status": "CATEGORY"` and titled with folder icons `📁 SectionName`).
* **Crawler Guard**: These virtual nodes are skipped during crawlers and audits (`status != "CATEGORY"`), so no attempt is made to visit non-existent intermediate routes.

---

## 5. Complete Reference Template (`example-map.json`)

```json
{
  "base_path": "/",
  "total_pages": 4,
  "nodes": {
    "/": {
      "path": "/",
      "title": "React App Home",
      "parent": null,
      "children": [
        "/login",
        "/advanced"
      ],
      "is_leaf": false,
      "depth": 0,
      "status": "OK",
      "error": false,
      "initialized": true,
      "initialized_at": "2026-07-27 12:00:00"
    },
    "/login": {
      "path": "/login",
      "title": "Authentication Gateway",
      "parent": "/",
      "children": [],
      "is_leaf": true,
      "depth": 1,
      "status": "OK",
      "error": false,
      "initialized": true,
      "initialized_at": "2026-07-27 12:01:00"
    },
    "/advanced": {
      "path": "/advanced",
      "title": "📁 Advanced Setup Menu",
      "parent": "/",
      "children": [
        "/advanced/network"
      ],
      "is_leaf": false,
      "depth": 1,
      "status": "CATEGORY",
      "error": false,
      "initialized": true,
      "initialized_at": "2026-07-27 12:02:00"
    },
    "/advanced/network": {
      "path": "/advanced/network",
      "title": "Network Parameters",
      "parent": "/advanced",
      "children": [],
      "is_leaf": true,
      "depth": 2,
      "status": "OK",
      "error": false,
      "initialized": true,
      "initialized_at": "2026-07-27 12:03:00",
      "verified_at": "2026-07-27 12:10:00",
      "dynamic_verified_at": "2026-07-27 12:15:00"
    }
  },
  "target_url": "http://localhost:8000",
  "default_username": "admin",
  "default_password": "admin",
  "main_task": "探索與初始化網站地圖 (Explore & Initialize Sitemap)",
  "page_path": "/overview",
  "wcag_sel": "None (不執行特定 WCAG 檢測)",
  "use_custom_model": false,
  "custom_model": "claude-3-5-sonnet-20241022",
  "model": "claude-sonnet-4-5 (預設)",
  "device": "desktop",
  "max_turns": 10,
  "headless": false,
  "record": true,
  "last_verified": "2026-07-27 12:20:00"
}
```

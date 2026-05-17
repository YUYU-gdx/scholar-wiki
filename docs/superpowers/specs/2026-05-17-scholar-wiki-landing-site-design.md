# Scholar Wiki Landing Site Design

## Goal

Build a static product website for Scholar Wiki. The site presents the product's research workflow and core capabilities to researchers, students, labs, and research teams. It does not embed the existing workbench, require a backend API, or expose a web app version of the desktop product.

The main conversion action is downloading or opening the desktop product release. If a release URL is not available during implementation, the download button should point to `#download` and use copy that makes the official release channel expectation clear.

## Audience

Primary audiences:

- Individual researchers and students who need to turn papers into searchable, evidence-backed knowledge.
- Lab or team leads who care about multi-library organization, traceable evidence, repeatable workflows, and team knowledge accumulation.

Secondary audience:

- Technical evaluators who want to understand the local-first architecture and integration model, but the page should not become a developer documentation site.

## Scope

In scope:

- A single static landing page served as the default website entry.
- Product positioning, workflow explanation, core feature sections, trust and evidence messaging, technical capability summary, and download calls to action.
- Static, responsive UI built from existing frontend stack assets.
- Deployment-compatible output for Alibaba Cloud static hosting.

Out of scope:

- Web workbench routing or `?app=workbench` mode.
- Live backend calls, user accounts, dashboards, document upload, chat, or graph interaction.
- Pricing, billing, analytics integrations, blog, documentation portal, or CMS.

## Site Structure

### Header

The header includes the Scholar Wiki brand, anchor links to page sections, and a compact primary action for downloading the desktop version. It stays visually restrained and should not dominate the first viewport.

### Hero

The first viewport makes Scholar Wiki the main signal. The headline should use the product name or a literal product category, with supporting copy explaining that the product converts academic papers into traceable knowledge graphs and evidence-based AI answers.

The visual side is a static product composition, not a live app: a knowledge graph panel, a cited evidence paragraph, and an AI answer panel. This communicates the workbench without making the website itself a workbench.

Primary CTA: "Download Desktop App"  
Secondary CTA: "Explore Features"

### Research Workflow

Show the product workflow as four concise steps:

1. Import PDFs or paper files.
2. Parse and normalize full text.
3. Extract variables, causal effects, moderation, and interaction relationships.
4. Explore the graph and ask evidence-backed questions.

The section should communicate a complete loop, not a collection of disconnected tools.

### Core Features

Feature modules:

- Literature Library: organize papers and libraries.
- Pipeline: automate parsing, extraction, indexing, and graph building.
- Knowledge Graph: explore variables and causal relationships.
- AI Q&A: answer research questions with retrievable evidence.
- Reader: inspect source papers, Markdown, annotations, and translations.

Each feature card should focus on user value and should avoid implementation detail.

### Trust Workflow

This section explains why researchers and teams can trust the product:

- Answers cite evidence paragraphs.
- Graph relationships retain source-paper context.
- Agent tool calls are visible and auditable.
- Multiple libraries can stay isolated or be compared.

### Team And Lab Value

Explain team-level use cases:

- Build a shared literature memory.
- Keep research areas separated by library.
- Reuse extracted variables and concepts across papers.
- Reduce repeated manual reading and extraction work.

This section should be practical and restrained, not enterprise-sales heavy.

### Technology Summary

Briefly mention:

- Local-first desktop workflow.
- React/Vite frontend.
- Python FastAPI backend in the desktop product.
- ChromaDB and SQLite indexes.
- MCP tools for retrieval and graph queries.
- Agent support for evidence-based research workflows.

This is a credibility section, not a developer reference.

### Final CTA

Repeat the download action and provide a secondary documentation or repository link if available. If a download target is unavailable, the implementation should use a single constant so the URL can be replaced without searching the codebase.

## Visual Direction

The website should feel like an academic research tool, not a generic SaaS landing page. Use a light, high-clarity interface with measured contrast, dense but readable information, and product-specific visuals. Avoid decorative gradient blobs, generic hero illustrations, and oversized marketing cards.

Visual principles:

- First viewport clearly signals Scholar Wiki and academic knowledge work.
- The hero visual should resemble real product surfaces: graph, evidence, and answer panes.
- Use existing palette foundations from `scholarai-workbench/src/index.css` where practical.
- Keep cards at 8px radius or less unless existing styles require otherwise.
- Use lucide icons for feature labels and actions.
- Ensure text fits on mobile and desktop without overlap.

## Technical Design

Implement the landing page inside `scholarai-workbench` using React, TypeScript, Vite, Tailwind, and lucide-react. The site should be static and build with `npm run build`.

Recommended implementation files:

- `scholarai-workbench/src/App.tsx`: render the landing page as the default experience for the website build.
- `scholarai-workbench/src/components/LandingPage.tsx`: product website sections.
- `scholarai-workbench/src/index.css`: only small shared style additions if needed.

The existing workbench code should remain in the repository, but the landing website should not route into it by default. Do not add a public web-workbench entry point as part of this feature.

## Alibaba Cloud Deployment Notes

The landing page should be deployable as static files. Alibaba Cloud OSS static website hosting supports publishing HTML, CSS, and JavaScript files from a Bucket as a public website, which fits this project because the public site has no server-side runtime.

Deployment constraints to respect:

- Build output must be plain static assets from Vite.
- Use `index.html` as the default homepage.
- Include a simple `error.html` or configure 404 behavior according to the chosen Alibaba Cloud product.
- Avoid client routes that require special SPA fallback rules unless the hosting configuration is known.
- Use relative asset paths compatible with Vite's generated `dist`.
- Bind a custom domain for normal browser access when using OSS static hosting.
- If the domain resolves to a China mainland region, plan for ICP filing before public launch.
- Configure HTTPS/SSL before sharing the production site.

Domain and hosting decisions:

- The likely brand domain is `scholarwiki.com` or a close variant, subject to domain availability and registration.
- The site should not depend on cookies, login, database access, or persistent server storage.
- A future download URL should be easy to update after releases are published.
- The initial desktop download URL should be stored in one constant. Until a release URL exists, point it to `#download` and show copy that frames the action as a desktop app download from the official release channel.
- Use the existing repository README as the secondary documentation target.
- Do not preserve an internal workbench launcher in the public landing page implementation.

## Error Handling

Since this is static marketing content, runtime error handling is minimal:

- Broken download links should be avoided by defining CTA URLs in one place.
- External links should open safely and have accessible labels.
- If a desktop release URL is not ready, CTA copy should avoid implying an unavailable download.
- The page should degrade gracefully if decorative visuals fail to load; core text and CTAs remain visible.

## Testing And Verification

Before completion:

- Run TypeScript/build verification with the existing frontend build command.
- Preview locally and check desktop and mobile widths.
- Verify the first viewport shows brand, value proposition, product visual, and download action.
- Verify no live API requests are required to render the website.
- Verify generated `dist` contains static files suitable for upload to Alibaba Cloud OSS or a static website service.

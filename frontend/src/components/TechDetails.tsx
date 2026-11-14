import type { ReactNode } from 'react'

// Job ids, supplier task ids, config revisions and billing caveats are needed for
// troubleshooting but distract creators; keep them one click away.
export function TechDetails({ children, summary = '技术详情' }: { children: ReactNode; summary?: string }) {
  return <details className="tech-details">
    <summary>{summary}</summary>
    <div className="tech-details-body">{children}</div>
  </details>
}

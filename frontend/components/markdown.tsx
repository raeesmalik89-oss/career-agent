import type { ReactNode } from "react";

/**
 * Renders the small Markdown subset the daily report uses (#/## headings, "- " bullets, paragraphs).
 * Text only: nothing is parsed as HTML, so report content can never inject markup.
 */
export function SimpleMarkdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) {
      blocks.push(
        <ul key={`ul-${blocks.length}`} className="mb-3 list-disc space-y-0.5 pl-5">
          {list.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  for (const line of text.split("\n")) {
    if (line.startsWith("- ")) {
      list.push(line.slice(2));
      continue;
    }
    flush();
    if (line.startsWith("## ")) {
      blocks.push(
        <h3 key={blocks.length} className="mb-1.5 mt-4 text-sm font-semibold first:mt-0">
          {line.slice(3)}
        </h3>,
      );
    } else if (line.startsWith("# ")) {
      blocks.push(
        <h2 key={blocks.length} className="mb-2 text-base font-semibold">
          {line.slice(2)}
        </h2>,
      );
    } else if (line.trim()) {
      blocks.push(
        <p key={blocks.length} className="mb-1.5">
          {line}
        </p>,
      );
    }
  }
  flush();
  return <div className="text-sm leading-relaxed">{blocks}</div>;
}

/** Vaqtinchalik sahifa — bo'lim hali qurilmagan (Bo'lim 10 bosqichma-bosqich). */

import { Panel, Eyebrow } from "@/components/ui/primitives";

export function ComingSoon({ title, source }: { title: string; source: string }) {
  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      <h1 className="text-xl font-bold">{title}</h1>
      <Panel className="mt-6 p-8 text-center">
        <Eyebrow>Qurilish navbatida</Eyebrow>
        <p className="mt-3 text-sm text-[var(--text-secondary)]">
          Bu sahifa keyingi bosqichda ulanadi. Backend manbasi:{" "}
          <code className="data text-[var(--accent-blue)]">{source}</code>
        </p>
      </Panel>
    </div>
  );
}

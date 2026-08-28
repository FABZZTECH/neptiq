import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Service index",
};

/*
 * Placeholder root route.
 *
 * ARCHITECTURE §16 is explicit that "a landing page exists" is NOT an
 * acceptance criterion, so Task 1 deliberately does not build marketing or
 * application UI. What this route DOES do is prove the shell is wired: fonts
 * load, tokens resolve, the layout renders, and the build passes with TS strict
 * and the invariant checks in place.
 *
 * The route groups app/(marketing), app/(auth) and app/(app) exist as empty
 * directories so the §5 structure is visible in the repository from the start
 * rather than being invented later.
 */
export default function IndexPage() {
  return (
    <main id="main" className="mx-auto w-full max-w-2xl px-6 py-16">
      <h1 className="font-mono text-sm tracking-widest text-on-surface-muted uppercase">
        NEPTIQ
      </h1>
      <p className="mt-4 text-2xl leading-snug text-on-surface">
        The system of record for search work.
      </p>
      <p className="mt-6 text-on-surface-muted">
        Application shell only. No product surface is implemented at this stage;
        see <code className="font-mono">docs/ARCHITECTURE.md</code> §16 for what
        completion actually requires.
      </p>
      <dl className="mt-10 space-y-3 border-t border-border-default pt-6 text-sm">
        <div className="flex gap-3">
          <dt className="w-40 shrink-0 text-on-surface-muted">Frontend</dt>
          <dd className="font-mono">Next.js 16.3.3 (App Router)</dd>
        </div>
        <div className="flex gap-3">
          <dt className="w-40 shrink-0 text-on-surface-muted">API</dt>
          <dd className="font-mono">FastAPI · Python 3.13</dd>
        </div>
        <div className="flex gap-3">
          <dt className="w-40 shrink-0 text-on-surface-muted">Data</dt>
          <dd className="font-mono">PostgreSQL 18 · RLS everywhere</dd>
        </div>
      </dl>
    </main>
  );
}

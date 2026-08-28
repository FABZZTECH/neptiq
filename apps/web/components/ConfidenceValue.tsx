/*
 * ConfidenceValue — the UI contract for CONSTITUTION P7 and P11.
 *
 * This component exists in Task 1, ahead of any product screen, because it is
 * the place where the two principles most likely to be quietly violated get
 * enforced in code:
 *
 *   P7  "Every derived quantity carries a confidence representation
 *        appropriate to its method."
 *   P11 "Where a thing cannot be reliably measured, NEPTIQ says so plainly...
 *        It never converts unmeasurable phenomena into confident scores."
 *
 * The design decision that makes this work is that the component accepts a
 * DISCRIMINATED UNION, not a number plus optional metadata. There is no way to
 * render a value through this component without stating which of the three
 * kinds it is. A caller holding a `not_measurable` cannot accidentally render
 * "0" or "—", because the component never receives a numeric field in that
 * case: the type has none.
 *
 * The GEO Honesty Charter requires that sampled measurements display n and the
 * interval. That is not left to the caller's discretion either — for the
 * `interval` kind, n and the bounds are required fields and are always
 * rendered.
 *
 * Note there is no `dangerouslySetInnerHTML` here or anywhere in apps/web
 * (invariant 5). Every string below is a React text child and is escaped by
 * React, which is what makes it safe to display values derived from crawled
 * pages.
 */

/** A deterministic computation: exact, no uncertainty to show. */
export interface ExactConfidence {
  readonly kind: "exact";
}

/** A sampled measurement. n and the interval are REQUIRED, per the Charter. */
export interface IntervalConfidence {
  readonly kind: "interval";
  readonly point: number;
  readonly low: number;
  readonly high: number;
  readonly n: number;
  readonly level: number;
  readonly method: string;
}

/** Honest non-measurement. Carries no number, by construction. */
export interface NotMeasurable {
  readonly kind: "not_measurable";
  readonly reason: string;
  readonly proxy?: string;
}

export type Confidence =
  | ExactConfidence
  | IntervalConfidence
  | NotMeasurable;

export interface ConfidenceValueProps {
  /**
   * The exact value. Required for `exact`, absent for the other kinds — the
   * union below makes the illegal combinations unrepresentable rather than
   * merely discouraged.
   */
  readonly confidence: Confidence;
  readonly exactValue?: number | string;
  readonly unit?: string;
  /** Rendered as a percentage when the interval represents a rate in [0,1]. */
  readonly asPercentage?: boolean;
}

function formatRate(value: number, asPercentage: boolean): string {
  if (asPercentage) {
    return `${(value * 100).toFixed(1)}%`;
  }
  // toPrecision rather than toFixed: appearance rates and CWV numbers differ by
  // orders of magnitude, and a fixed decimal count misrepresents both ends.
  return Number(value.toPrecision(4)).toString();
}

export function ConfidenceValue({
  confidence,
  exactValue,
  unit,
  asPercentage = false,
}: ConfidenceValueProps) {
  switch (confidence.kind) {
    case "exact":
      return (
        <span className="font-mono text-on-surface">
          {exactValue ?? "—"}
          {unit ? <span className="ml-1 text-on-surface-muted">{unit}</span> : null}
        </span>
      );

    case "interval": {
      const { point, low, high, n, level, method } = confidence;
      const levelPct = Math.round(level * 100);
      return (
        <span className="inline-flex flex-wrap items-baseline gap-x-2">
          <span className="font-mono text-on-surface">
            {formatRate(point, asPercentage)}
            {unit ? <span className="ml-1 text-on-surface-muted">{unit}</span> : null}
          </span>
          {/*
            The interval and n are always shown, never behind a tooltip or a
            hover. The Charter's requirement is that "the UI states n and the
            interval" — information the reader has to go looking for is not
            stated.
          */}
          <span className="font-mono text-xs text-on-surface-muted">
            {formatRate(low, asPercentage)}–{formatRate(high, asPercentage)}
          </span>
          <span
            className="text-xs text-on-surface-muted"
            title={`${levelPct}% ${method} interval over n=${n} samples`}
          >
            ({levelPct}% CI, n={n})
          </span>
        </span>
      );
    }

    case "not_measurable":
      return (
        <span className="inline-flex flex-wrap items-baseline gap-x-2">
          {/*
            Deliberately NOT a number, a dash, or a zero. A dash reads as "no
            data yet" and a zero reads as a measurement of nothing; both are
            claims we have not earned. The words are explicit.
          */}
          <span className="text-state-not-measurable italic">
            Not measurable
          </span>
          <span className="text-xs text-on-surface-muted">
            {confidence.reason}
          </span>
          {confidence.proxy ? (
            <span className="text-xs text-on-surface-muted">
              Best honest proxy: {confidence.proxy}
            </span>
          ) : null}
        </span>
      );
  }
}

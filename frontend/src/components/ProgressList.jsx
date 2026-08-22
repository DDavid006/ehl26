function Spinner() {
  return (
    <span
      role="status"
      aria-label="working"
      className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-slate-300 border-t-slate-900"
    />
  )
}

// steps is an array of strings; the last one carries the spinner while running.
export default function ProgressList({ steps, running }) {
  if (steps.length === 0) return null

  return (
    <section className="rounded-md border border-slate-200 bg-slate-50 p-4">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Progress
      </h2>
      <ol className="space-y-2">
        {steps.map((step, index) => {
          const isLast = index === steps.length - 1
          return (
            <li key={`${index}-${step}`} className="flex items-start gap-2 text-sm text-slate-700">
              {isLast && running ? (
                <Spinner />
              ) : (
                <span className="mt-0.5 h-3.5 w-3.5 shrink-0 text-center text-xs leading-none text-slate-400">
                  ✓
                </span>
              )}
              <span className={isLast && running ? 'font-medium text-slate-900' : ''}>{step}</span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

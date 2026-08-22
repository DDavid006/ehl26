export default function SuggestionCards({ suggestions, patents }) {
  const patentById = new Map(patents.map((patent) => [patent.id, patent]))

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold text-slate-900">Suggestions</h2>
      <ul className="space-y-3">
        {suggestions.map((suggestion, index) => {
          const patent = patentById.get(suggestion.patent)
          return (
            <li
              key={suggestion.id ?? index}
              className="rounded-md border border-slate-200 bg-white p-4 shadow-sm"
            >
              <h3 className="font-semibold text-slate-900">{suggestion.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{suggestion.reasoning}</p>
              <p className="mt-3 text-xs text-slate-500">
                Referenced patent:{' '}
                <span className="font-mono text-slate-700">
                  {patent ? patent.number : suggestion.patent}
                </span>
                {patent ? ` — ${patent.title}` : null}
              </p>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

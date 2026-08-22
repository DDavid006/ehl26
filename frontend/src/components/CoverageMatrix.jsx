function CoveredCell({ evidence, patent, element }) {
  return (
    <td className="border border-slate-200 p-0">
      <div className="group relative flex h-16 items-center justify-center bg-slate-800">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-100">
          covered
        </span>
        <div className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 hidden w-80 -translate-x-1/2 rounded-md bg-slate-900 p-3 text-left text-xs leading-relaxed text-slate-100 shadow-xl group-hover:block">
          <div className="mb-1 font-semibold text-white">
            {patent.number} — {element.label}
          </div>
          {evidence}
        </div>
      </div>
    </td>
  )
}

function UncoveredCell() {
  return (
    <td className="border border-slate-200 p-0">
      <div className="flex h-16 items-center justify-center bg-green-400">
        <span className="text-sm font-black uppercase tracking-widest text-green-950">
          open
        </span>
      </div>
    </td>
  )
}

export default function CoverageMatrix({ elements, patents, coverage, uncovered }) {
  const uncoveredSet = new Set(uncovered ?? [])

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold text-slate-900">Coverage matrix</h2>
        <p className="text-sm text-slate-500">
          <span className="mr-1 inline-block h-3 w-3 rounded-sm bg-green-400 align-middle" />
          bright green = no patent covers this element
        </p>
      </div>

      <div className="overflow-x-auto rounded-md border border-slate-200">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr>
              <th className="w-80 border border-slate-200 bg-slate-50 p-3 text-left align-bottom font-semibold text-slate-700">
                Element
              </th>
              {patents.map((patent) => (
                <th
                  key={patent.id}
                  className="border border-slate-200 bg-slate-50 p-3 text-left align-bottom font-semibold text-slate-700"
                >
                  <div className="font-mono text-xs text-slate-900">{patent.number}</div>
                  <div className="mt-1 max-w-[12rem] text-xs font-normal text-slate-500">
                    {patent.title}
                  </div>
                  <div className="text-xs font-normal italic text-slate-400">{patent.assignee}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {elements.map((element) => {
              const row = coverage?.[element.id] ?? {}
              const isOpenRow = uncoveredSet.has(element.id) || patents.every((p) => !row[p.id])
              return (
                <tr key={element.id} className={isOpenRow ? 'bg-green-50' : undefined}>
                  <th
                    scope="row"
                    className="border border-slate-200 p-3 text-left align-top font-normal"
                  >
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      {element.label}
                    </div>
                    <div className="mt-1 text-slate-800">{element.text}</div>
                  </th>
                  {patents.map((patent) => {
                    const cell = row[patent.id]
                    return cell ? (
                      <CoveredCell
                        key={patent.id}
                        evidence={cell.evidence ?? String(cell)}
                        patent={patent}
                        element={element}
                      />
                    ) : (
                      <UncoveredCell key={patent.id} />
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

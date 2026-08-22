export default function DescriptionForm({ value, onChange, onSubmit, busy }) {
  return (
    <section className="space-y-3">
      <label htmlFor="description" className="block text-sm font-medium text-slate-700">
        Describe your invention
      </label>
      <textarea
        id="description"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        rows={10}
        placeholder="What it is, what it does, and which features you think are new…"
        className="w-full resize-y rounded-md border border-slate-300 p-4 text-sm leading-relaxed text-slate-900 shadow-sm outline-none focus:border-slate-500 focus:ring-1 focus:ring-slate-500"
      />
      <button
        type="button"
        onClick={onSubmit}
        disabled={busy || value.trim() === ''}
        className="rounded-md bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300"
      >
        {busy ? 'Analysing…' : 'Analyse'}
      </button>
    </section>
  )
}

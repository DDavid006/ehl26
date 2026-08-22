import { useState } from 'react'
import DescriptionForm from './components/DescriptionForm.jsx'
import ProgressList from './components/ProgressList.jsx'
import CoverageMatrix from './components/CoverageMatrix.jsx'
import SuggestionCards from './components/SuggestionCards.jsx'
import { analyse, USE_MOCK_DEFAULT } from './api.js'

export default function App() {
  const [description, setDescription] = useState('')
  const [useMock, setUseMock] = useState(USE_MOCK_DEFAULT)
  const [steps, setSteps] = useState([])
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  async function runAnalysis() {
    setRunning(true)
    setResult(null)
    setError(null)
    setSteps([])
    try {
      const data = await analyse(description, {
        useMock,
        onProgress: (step) => setSteps((current) => [...current, step]),
      })
      setResult(data)
      setSteps((current) => [...current, 'Done'])
    } catch (caught) {
      setError(caught.message)
      setSteps((current) => [...current, 'Failed'])
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <div className="mx-auto max-w-6xl space-y-10 px-6 py-10">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <h1 className="text-2xl font-semibold tracking-tight">Patent clearance</h1>
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={useMock}
              onChange={(event) => setUseMock(event.target.checked)}
              className="h-4 w-4 rounded border-slate-400"
            />
            Use mock data
          </label>
        </header>

        <DescriptionForm
          value={description}
          onChange={setDescription}
          onSubmit={runAnalysis}
          busy={running}
        />

        <ProgressList steps={steps} running={running} />

        {error ? (
          <p className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {error}
          </p>
        ) : null}

        {result ? (
          <section className="space-y-8">
            <CoverageMatrix
              elements={result.elements ?? []}
              patents={result.patents ?? []}
              coverage={result.coverage ?? {}}
              uncovered={result.uncovered ?? []}
            />
            <SuggestionCards
              suggestions={result.suggestions ?? []}
              patents={result.patents ?? []}
            />
          </section>
        ) : null}
      </div>
    </div>
  )
}

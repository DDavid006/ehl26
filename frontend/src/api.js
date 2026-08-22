import mockData from './mockData.js'

// Default source is chosen by VITE_USE_MOCK; the header toggle overrides it at runtime.
export const USE_MOCK_DEFAULT = import.meta.env.VITE_USE_MOCK !== 'false'

const MOCK_PROGRESS = [
  'Extracting claim elements from the description',
  'Dispatching 5 prior-art searchers',
  'USPTO full-text search: 34 hits, 6 opened',
  'CPC sweep: A61B 5/02, A61B 5/145',
  'Comparing claim elements against opened references',
  'Assembling coverage matrix',
]

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

export async function analyseMock(_description, onProgress) {
  for (const step of MOCK_PROGRESS) {
    onProgress(step)
    await sleep(700)
  }
  return mockData
}

export async function analyseReal(description, onProgress) {
  onProgress('POST /api/analyse')
  const response = await fetch('/api/analyse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description }),
  })
  if (!response.ok) {
    throw new Error(`/api/analyse failed with ${response.status} ${response.statusText}`)
  }
  onProgress('Rendering results')
  return response.json()
}

export function analyse(description, { useMock, onProgress }) {
  return useMock ? analyseMock(description, onProgress) : analyseReal(description, onProgress)
}

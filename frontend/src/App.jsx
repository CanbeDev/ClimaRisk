import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, Globe2, LineChart, Loader2, Map as MapIcon, RefreshCw } from 'lucide-react'
import MapPanel from './components/MapPanel'
import ExposurePanel from './components/ExposurePanel'
import { fetchAssets, fetchHazards, fetchIntersection, fetchTrends } from './api'

// Code-split the trend view: it pulls in recharts (~450 kB), and the map is the
// default view most sessions never leave. Loaded on first switch to Trends.
const TrendsPanel = lazy(() => import('./components/TrendsPanel'))

export default function App() {
  const [view, setView] = useState('map') // 'map' | 'trends'

  const [hazards, setHazards] = useState(null)
  const [assets, setAssets] = useState(null)
  const [mapLoading, setMapLoading] = useState(true)
  const [mapError, setMapError] = useState(null)

  const [selectedHazardId, setSelectedHazardId] = useState(null)
  const [intersection, setIntersection] = useState(null)
  const [loadingIntersection, setLoadingIntersection] = useState(false)
  const [intersectionError, setIntersectionError] = useState(null)

  const [trends, setTrends] = useState(null)
  const [trendsLoading, setTrendsLoading] = useState(false)
  const [trendsError, setTrendsError] = useState(null)

  const loadMapData = useCallback(async () => {
    setMapLoading(true)
    setMapError(null)
    try {
      const [hazardData, assetData] = await Promise.all([fetchHazards(), fetchAssets()])
      setHazards(hazardData)
      setAssets(assetData)
    } catch (err) {
      setMapError(err.message || 'Failed to load map data')
    } finally {
      setMapLoading(false)
    }
  }, [])

  useEffect(() => {
    loadMapData()
  }, [loadMapData])

  const loadTrends = useCallback(async () => {
    setTrendsLoading(true)
    setTrendsError(null)
    try {
      setTrends(await fetchTrends())
    } catch (err) {
      setTrendsError(err.message || 'Failed to load hazard history')
    } finally {
      setTrendsLoading(false)
    }
  }, [])

  // Lazy-load the trend series the first time the user opens that view — the
  // map is the default and most sessions never switch, so there's no reason to
  // pay for /trends/hazards on initial load.
  useEffect(() => {
    if (view === 'trends' && trends == null && !trendsLoading && !trendsError) {
      loadTrends()
    }
  }, [view, trends, trendsLoading, trendsError, loadTrends])

  // Guards against out-of-order responses: if the user selects hazard A then B before A's
  // request resolves, only the response matching the *current* request id is applied — a
  // late-arriving response for a since-superseded selection is dropped instead of overwriting
  // newer state.
  const intersectionRequestRef = useRef(0)

  const loadIntersection = useCallback(async (hazardEventId) => {
    const requestId = ++intersectionRequestRef.current
    setLoadingIntersection(true)
    setIntersectionError(null)
    try {
      const result = await fetchIntersection(hazardEventId)
      if (intersectionRequestRef.current !== requestId) return
      setIntersection(result)
    } catch (err) {
      if (intersectionRequestRef.current !== requestId) return
      setIntersectionError(
        err.status === 404 ? 'This hazard event no longer exists.' : err.message || 'Failed to compute exposure.',
      )
      setIntersection(null)
    } finally {
      if (intersectionRequestRef.current === requestId) {
        setLoadingIntersection(false)
      }
    }
  }, [])

  const handleSelectHazard = useCallback(
    (hazardEventId) => {
      setSelectedHazardId(hazardEventId)
      loadIntersection(hazardEventId)
    },
    [loadIntersection],
  )

  const selectedHazardMeta = useMemo(() => {
    if (!hazards || selectedHazardId == null) return null
    const feature = hazards.features.find((f) => f.properties.hazard_event_id === selectedHazardId)
    return feature ? feature.properties : null
  }, [hazards, selectedHazardId])

  const exposedAssetIds = useMemo(() => {
    if (!intersection) return new Set()
    return new Set(intersection.assets.map((asset) => asset.id))
  }, [intersection])

  const onTrends = view === 'trends'
  const activeError = onTrends ? trendsError : mapError
  const activeSpinning = onTrends ? trendsLoading : mapLoading
  const handleRefresh = () => (onTrends ? loadTrends() : loadMapData())

  return (
    <div className="flex h-screen w-screen flex-col bg-slate-950 text-slate-100">
      <header className="flex shrink-0 items-center justify-between border-b border-slate-800 bg-slate-900/80 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Globe2 className="h-5 w-5 text-cyan-400" />
          <div>
            <div className="text-sm font-semibold leading-tight">ClimRisk Command Center</div>
            <div className="text-[11px] leading-tight text-slate-500">
              GDACS × PostGIS exposure intelligence — South Africa
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center rounded border border-slate-800 p-0.5 text-xs">
            <button
              onClick={() => setView('map')}
              className={`flex items-center gap-1.5 rounded px-2 py-1 ${
                view === 'map' ? 'bg-slate-800 text-slate-100' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <MapIcon className="h-3.5 w-3.5" />
              Live map
            </button>
            <button
              onClick={() => setView('trends')}
              className={`flex items-center gap-1.5 rounded px-2 py-1 ${
                view === 'trends' ? 'bg-slate-800 text-slate-100' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <LineChart className="h-3.5 w-3.5" />
              Trends
            </button>
          </div>
          {activeError && (
            <span className="flex items-center gap-1 text-xs text-rose-400">
              <AlertTriangle className="h-3.5 w-3.5" />
              {activeError}
            </span>
          )}
          <button
            onClick={handleRefresh}
            className="flex items-center gap-1.5 rounded border border-slate-800 px-2 py-1 text-xs text-slate-400 hover:text-slate-200"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${activeSpinning ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <span className="flex items-center gap-1.5 text-xs text-emerald-400">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
            Live
          </span>
        </div>
      </header>

      <main className="flex flex-1 overflow-hidden">
        {view === 'map' ? (
          <>
            <div className="h-full w-[65%] border-r border-slate-800">
              <MapPanel
                hazards={hazards}
                assets={assets}
                selectedHazardId={selectedHazardId}
                exposedAssetIds={exposedAssetIds}
                onSelectHazard={handleSelectHazard}
              />
            </div>
            <div className="h-full w-[35%]">
              <ExposurePanel
                selectedHazardMeta={selectedHazardMeta}
                intersection={intersection}
                loading={loadingIntersection}
                error={intersectionError}
                onRetry={() => selectedHazardId != null && loadIntersection(selectedHazardId)}
              />
            </div>
          </>
        ) : (
          <div className="h-full w-full">
            <Suspense
              fallback={
                <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading trend view…
                </div>
              }
            >
              <TrendsPanel
                trends={trends}
                loading={trendsLoading}
                error={trendsError}
                onRetry={loadTrends}
              />
            </Suspense>
          </div>
        )}
      </main>
    </div>
  )
}

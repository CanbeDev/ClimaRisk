import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  FileText,
  Globe2,
  LineChart,
  Map as MapIcon,
  RefreshCw,
  ShieldAlert,
} from 'lucide-react'
import MapPanel from './components/MapPanel'
import ExposurePanel from './components/ExposurePanel'
import { SkeletonCards, SkeletonRows } from './components/Skeleton'
import {
  fetchAssets,
  fetchDisclosure,
  fetchFirings,
  fetchHazards,
  fetchIntersection,
  fetchParametricSummary,
  fetchTrends,
  fetchTriggers,
} from './api'

// Code-split the non-default views: Trends pulls in recharts (~450 kB), and most
// sessions never leave the map. Each loads on first switch to it.
const TrendsPanel = lazy(() => import('./components/TrendsPanel'))
const ParametricPanel = lazy(() => import('./components/ParametricPanel'))
const ReportPanel = lazy(() => import('./components/ReportPanel'))

const VIEWS = [
  { id: 'map', label: 'Live map', icon: MapIcon },
  { id: 'trends', label: 'Trends', icon: LineChart },
  { id: 'parametric', label: 'Parametric', icon: ShieldAlert },
  { id: 'report', label: 'Report', icon: FileText },
]

// Connection status pill — reflects the real fetch state, not decoration:
// amber pulse while a request is in flight, rose when the last one failed,
// green + relative time when data is current, muted when it's gone stale.
function describeConnection(lastSyncAt, error, spinning, now) {
  if (spinning) return { cls: 'text-over', dot: 'bg-over animate-pulse', label: 'Syncing…' }
  if (error) {
    return {
      cls: 'text-pml',
      dot: 'bg-pml',
      label: 'Connection lost',
      title: typeof error === 'string' ? error : undefined,
    }
  }
  if (!lastSyncAt) return { cls: 'text-muted', dot: 'bg-muted', label: 'Connecting…' }
  const secs = Math.max(0, Math.round((now - lastSyncAt) / 1000))
  const stale = secs > 120
  return {
    cls: stale ? 'text-muted' : 'text-ok',
    dot: stale ? 'bg-muted' : 'bg-ok',
    label: secs < 10 ? 'Live' : secs < 60 ? `Live · ${secs}s ago` : `Synced ${Math.round(secs / 60)}m ago`,
    title: `Last successful fetch: ${new Date(lastSyncAt).toLocaleTimeString('en-ZA')}`,
  }
}

function ConnectionStatus({ lastSyncAt, error, spinning }) {
  // A slow clock so the relative label stays current without touching Date.now()
  // during render (it only runs while idle and connected).
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (spinning || error || !lastSyncAt) return undefined
    const id = setInterval(() => setNow(Date.now()), 10_000)
    return () => clearInterval(id)
  }, [spinning, error, lastSyncAt])

  const s = describeConnection(lastSyncAt, error, spinning, Math.max(now, lastSyncAt ?? 0))

  return (
    <span className={`flex items-center gap-1.5 text-xs font-medium ${s.cls}`} title={s.title}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  )
}

export default function App() {
  const [view, setView] = useState('map') // 'map' | 'trends' | 'parametric' | 'report'

  const [lastSyncAt, setLastSyncAt] = useState(null)

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

  const [parametric, setParametric] = useState(null)
  const [parametricLoading, setParametricLoading] = useState(false)
  const [parametricError, setParametricError] = useState(null)

  const [report, setReport] = useState(null)
  const [reportLoading, setReportLoading] = useState(false)
  const [reportError, setReportError] = useState(null)

  const loadMapData = useCallback(async () => {
    setMapLoading(true)
    setMapError(null)
    try {
      const [hazardData, assetData] = await Promise.all([fetchHazards(), fetchAssets()])
      setHazards(hazardData)
      setAssets(assetData)
      setLastSyncAt(Date.now())
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
      setLastSyncAt(Date.now())
    } catch (err) {
      setTrendsError(err.message || 'Failed to load hazard history')
    } finally {
      setTrendsLoading(false)
    }
  }, [])

  const loadParametric = useCallback(async () => {
    setParametricLoading(true)
    setParametricError(null)
    try {
      const [summary, triggers, firings] = await Promise.all([
        fetchParametricSummary(),
        fetchTriggers(),
        fetchFirings(),
      ])
      setParametric({ summary, triggers: triggers.triggers, firings: firings.firings })
      setLastSyncAt(Date.now())
    } catch (err) {
      setParametricError(err.message || 'Failed to load parametric data')
    } finally {
      setParametricLoading(false)
    }
  }, [])

  const loadReport = useCallback(async (from, to) => {
    setReportLoading(true)
    setReportError(null)
    try {
      setReport(await fetchDisclosure(from, to))
      setLastSyncAt(Date.now())
    } catch (err) {
      setReportError(err.message || 'Failed to build disclosure report')
    } finally {
      setReportLoading(false)
    }
  }, [])

  // Lazy-load each non-default view's data the first time it's opened.
  useEffect(() => {
    if (view === 'trends' && trends == null && !trendsLoading && !trendsError) loadTrends()
    if (view === 'parametric' && parametric == null && !parametricLoading && !parametricError) {
      loadParametric()
    }
    if (view === 'report' && report == null && !reportLoading && !reportError) loadReport()
  }, [
    view,
    trends,
    trendsLoading,
    trendsError,
    loadTrends,
    parametric,
    parametricLoading,
    parametricError,
    loadParametric,
    report,
    reportLoading,
    reportError,
    loadReport,
  ])

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
      setLastSyncAt(Date.now())
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

  const { activeError, activeSpinning, handleRefresh } = useMemo(() => {
    if (view === 'trends') {
      return { activeError: trendsError, activeSpinning: trendsLoading, handleRefresh: loadTrends }
    }
    if (view === 'parametric') {
      return {
        activeError: parametricError,
        activeSpinning: parametricLoading,
        handleRefresh: loadParametric,
      }
    }
    if (view === 'report') {
      return { activeError: reportError, activeSpinning: reportLoading, handleRefresh: () => loadReport() }
    }
    return { activeError: mapError, activeSpinning: mapLoading, handleRefresh: loadMapData }
  }, [
    view,
    trendsError,
    trendsLoading,
    loadTrends,
    parametricError,
    parametricLoading,
    loadParametric,
    reportError,
    reportLoading,
    loadReport,
    mapError,
    mapLoading,
    loadMapData,
  ])

  return (
    <div className="relative flex h-screen w-screen flex-col bg-ground text-ink">
      <div className="app-bg" aria-hidden="true" />
      <header className="relative z-10 flex shrink-0 items-center justify-between bg-surface/85 px-5 py-3 shadow-[0_1px_0_rgba(40,28,16,0.06),0_6px_16px_-10px_rgba(40,28,16,0.14)] backdrop-blur-sm">
        <div className="flex items-center gap-2.5">
          <Globe2 className="h-5 w-5 text-brand" />
          <div>
            <div className="text-[15px] font-semibold leading-tight">ClimRisk Command Center</div>
            <div className="text-[11px] leading-tight text-muted">
              GDACS × PostGIS exposure intelligence — South Africa
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-0.5 rounded-lg bg-sunken p-1 text-xs">
            {VIEWS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setView(id)}
                className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 font-medium transition-colors ${
                  view === id
                    ? 'bg-brandsoft text-brand shadow-sm'
                    : 'text-muted hover:text-ink'
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </button>
            ))}
          </div>
          {activeError && (
            <span className="flex items-center gap-1 text-xs text-pml">
              <AlertTriangle className="h-3.5 w-3.5" />
              {activeError}
            </span>
          )}
          <button
            onClick={handleRefresh}
            className="flex items-center gap-1.5 rounded-md bg-surface px-2.5 py-1.5 text-xs text-muted shadow-sm ring-1 ring-hair transition hover:text-ink hover:ring-[#d8cfc2]"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${activeSpinning ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <ConnectionStatus lastSyncAt={lastSyncAt} error={activeError} spinning={activeSpinning} />
        </div>
      </header>

      <main className="relative z-10 flex flex-1 overflow-hidden">
        {view === 'map' && (
          <>
            <div className="h-full w-[64%]">
              <MapPanel
                hazards={hazards}
                assets={assets}
                selectedHazardId={selectedHazardId}
                exposedAssetIds={exposedAssetIds}
                onSelectHazard={handleSelectHazard}
              />
            </div>
            <div className="h-full w-[36%] border-l border-hair bg-ground">
              <ExposurePanel
                selectedHazardMeta={selectedHazardMeta}
                intersection={intersection}
                loading={loadingIntersection}
                error={intersectionError}
                onRetry={() => selectedHazardId != null && loadIntersection(selectedHazardId)}
              />
            </div>
          </>
        )}

        {view !== 'map' && (
          <div className="h-full w-full">
            <Suspense
              fallback={
                <div className="mx-auto flex h-full max-w-5xl flex-col gap-5 p-6">
                  <SkeletonCards count={4} hero />
                  <SkeletonRows rows={5} />
                </div>
              }
            >
              {view === 'trends' && (
                <TrendsPanel
                  trends={trends}
                  loading={trendsLoading}
                  error={trendsError}
                  onRetry={loadTrends}
                />
              )}
              {view === 'parametric' && (
                <ParametricPanel
                  summary={parametric?.summary}
                  triggers={parametric?.triggers}
                  firings={parametric?.firings}
                  loading={parametricLoading}
                  error={parametricError}
                  onChanged={loadParametric}
                />
              )}
              {view === 'report' && (
                <ReportPanel
                  report={report}
                  loading={reportLoading}
                  error={reportError}
                  onReload={loadReport}
                />
              )}
            </Suspense>
          </div>
        )}
      </main>
    </div>
  )
}

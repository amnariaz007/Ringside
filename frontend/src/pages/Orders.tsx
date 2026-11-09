import { useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AgGridReact } from 'ag-grid-react'
import type { CustomCellRendererProps } from 'ag-grid-react'
import type { ColDef } from 'ag-grid-community'
import { api } from '../api'
import type { Level, OrderRow } from '../api'
import { Async, PageHeader, ProtectionBadge } from '../components'
import { dateTime, money } from '../format'
import { exportName, ledgerTheme } from '../grid'
import { useLoad } from '../hooks'
import { RiskCell } from '../visuals'

const FILTERS: { value: Level | ''; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
]

// Short, human labels for rule codes shown as chips.
const RULE_LABEL: Record<string, string> = {
  NOT_SELLER_PROTECTED: 'no protection',
  COUNTRY_MISMATCH: 'country',
  RESHIPPER_ADDRESS: 'forwarder',
  UNUSUAL_AMOUNT: 'amount',
  VELOCITY: 'velocity',
  DISPOSABLE_EMAIL: 'disposable email',
  UNVERIFIED_PAYER: 'unverified',
  REFUND_HABIT: 'refund habit',
  PRIOR_DISPUTES: 'disputes',
  LINKED_TO_BAD_ACTOR: 'ring link',
}

// The strongest fraud signals get a red chip.
const ALERT_RULES = new Set(['LINKED_TO_BAD_ACTOR', 'RESHIPPER_ADDRESS', 'PRIOR_DISPUTES'])

function BuyerCell(p: CustomCellRendererProps<OrderRow>) {
  return (
    <span className="cell-two">
      <strong>{p.data?.buyer}</strong>
      <small>{p.data?.payer_id}</small>
    </span>
  )
}

function SignalsCell(p: CustomCellRendererProps<OrderRow>) {
  const rules = p.data?.rules ?? []
  if (!rules.length) return <span className="muted small">none</span>
  return (
    <span className="chips">
      {rules.slice(0, 3).map((r) => (
        <span key={r} className={`chip ${ALERT_RULES.has(r) ? 'chip-alert' : ''}`}>{RULE_LABEL[r] ?? r}</span>
      ))}
      {rules.length > 3 && <span className="more">+{rules.length - 3}</span>}
    </span>
  )
}

function RouteCell(p: CustomCellRendererProps<OrderRow>) {
  const o = p.data
  if (!o) return null
  const mismatch = o.payer_country && o.ship_country && o.payer_country !== o.ship_country
  return <span className={mismatch ? 'route-mismatch' : 'muted'}>{o.payer_country || '—'} → {o.ship_country || '—'}</span>
}

export default function Orders() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const level = (params.get('level') ?? '') as Level | ''
  const [query, setQuery] = useState('')
  const grid = useRef<AgGridReact<OrderRow>>(null)
  const state = useLoad(() => api.orders(), [])

  const rows = useMemo(
    () => (state.data?.results ?? []).filter((o) => !level || o.level === level),
    [state.data, level],
  )

  const columns = useMemo<ColDef<OrderRow>[]>(() => [
    {
      headerName: 'Risk', field: 'score', width: 130, sort: 'desc',
      cellRenderer: (p: CustomCellRendererProps<OrderRow>) => <RiskCell score={p.data?.score ?? null} level={p.data?.level ?? null} />,
      filter: 'agNumberColumnFilter',
    },
    { headerName: 'Buyer', field: 'buyer', flex: 1.3, minWidth: 180, cellRenderer: BuyerCell, filter: 'agTextColumnFilter',
      getQuickFilterText: (p) => `${p.data?.buyer} ${p.data?.payer_id}` },
    { headerName: 'Why', field: 'rules', flex: 1.6, minWidth: 300, sortable: false, cellRenderer: SignalsCell,
      valueFormatter: (p) => (p.value ?? []).join(' '), getQuickFilterText: (p) => (p.data?.rules ?? []).map((r) => RULE_LABEL[r] ?? r).join(' ') },
    { headerName: 'Placed', field: 'created_at', width: 150, valueFormatter: (p) => (p.value ? dateTime(p.value) : '') },
    { headerName: 'Route', colId: 'route', width: 110, sortable: false, cellRenderer: RouteCell,
      valueGetter: (p) => `${p.data?.payer_country}->${p.data?.ship_country}` },
    { headerName: 'Protection', field: 'seller_protection', width: 150,
      cellRenderer: (p: CustomCellRendererProps<OrderRow>) => <ProtectionBadge status={p.value ?? ''} />, filter: 'agTextColumnFilter' },
    { headerName: 'Amount', field: 'amount', width: 120, type: 'rightAligned', comparator: (a, b) => Number(a) - Number(b),
      valueFormatter: (p) => (p.data ? money(p.value, p.data.currency) : ''), filter: 'agNumberColumnFilter',
      filterValueGetter: (p) => Number(p.data?.amount) },
  ], [])

  return (
    <>
      <PageHeader eyebrow="Orders" title="Every order, scored on arrival"
        subtitle="Each PayPal order gets a 0–100 risk score with its reasons. Click a row to see the evidence." />
      <Async state={state}>
        {(page) => (
          <>
            <div className="grid-meta">
              <div className="toolbar">
                <div className="segmented" role="tablist" aria-label="Filter by risk level">
                  {FILTERS.map((f) => (
                    <button key={f.label} role="tab" aria-selected={level === f.value}
                      className={level === f.value ? 'active' : ''}
                      onClick={() => setParams(f.value ? { level: f.value } : {})}>
                      {f.label}
                    </button>
                  ))}
                </div>
                <input className="search" type="search" placeholder="Search buyer, payer ID or reason"
                  aria-label="Search orders" value={query} onChange={(e) => setQuery(e.target.value)} />
              </div>
              <div className="toolbar">
                <span className="muted small">{rows.length} of {page.count} orders</span>
                <button className="button" onClick={() => grid.current?.api.exportDataAsCsv({ fileName: exportName('orders') })}>
                  Export CSV
                </button>
              </div>
            </div>
            <div className="grid-frame">
              <AgGridReact<OrderRow>
                ref={grid}
                theme={ledgerTheme}
                rowData={rows}
                columnDefs={columns}
                defaultColDef={{ sortable: true, resizable: true, suppressHeaderMenuButton: true }}
                quickFilterText={query}
                getRowId={(p) => String(p.data.id)}
                pagination
                paginationPageSize={20}
                paginationPageSizeSelector={[20, 50, 100]}
                onRowClicked={(e) => e.data && navigate(`/orders/${e.data.id}`)}
                overlayNoRowsTemplate="No orders match these filters."
              />
            </div>
          </>
        )}
      </Async>
    </>
  )
}

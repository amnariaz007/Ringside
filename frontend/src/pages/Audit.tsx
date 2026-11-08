import { useMemo, useRef, useState } from 'react'
import { AgGridReact } from 'ag-grid-react'
import type { CustomCellRendererProps } from 'ag-grid-react'
import type { ColDef } from 'ag-grid-community'
import { api } from '../api'
import type { AuditRow } from '../api'
import { Async, PageHeader } from '../components'
import { dateTime } from '../format'
import { exportName, ledgerTheme } from '../grid'
import { useLoad } from '../hooks'

const ACTORS = ['', 'paypal', 'system', 'ai', 'seller'] as const

function summarize(payload: Record<string, unknown>): string {
  if (typeof payload.text === 'string') return payload.text
  return Object.entries(payload)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') || '—' : typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
    .join(' · ')
}

export default function Audit() {
  const [actor, setActor] = useState<string>('')
  const [query, setQuery] = useState('')
  const grid = useRef<AgGridReact<AuditRow>>(null)
  const state = useLoad(() => api.audit(), [])
  const rows = useMemo(() => (state.data?.results ?? []).filter((r) => !actor || r.actor === actor), [state.data, actor])

  const columns = useMemo<ColDef<AuditRow>[]>(() => [
    { headerName: 'When', field: 'created_at', width: 150, sort: 'desc', valueFormatter: (p) => (p.value ? dateTime(p.value) : '') },
    { headerName: 'Actor', field: 'actor', width: 110,
      cellRenderer: (p: CustomCellRendererProps<AuditRow>) => <span className={`actor actor-${p.value}`}>{p.value}</span> },
    { headerName: 'Action', field: 'action', width: 220, cellClass: 'mono' },
    { headerName: 'PayPal ID', field: 'paypal_id', width: 210, cellClass: 'mono' },
    { headerName: 'Details', colId: 'details', flex: 1, minWidth: 260, tooltipValueGetter: (p) => p.value,
      valueGetter: (p) => (p.data ? summarize(p.data.payload) : '') },
  ], [])

  return (
    <>
      <PageHeader eyebrow="Audit log" title="Every decision, on the record"
        subtitle="Each score, AI output, seller decision and PayPal call, with its PayPal ID." />
      <Async state={state}>
        {(page) => (
          <>
            <div className="grid-meta">
              <div className="toolbar">
                <div className="segmented" role="tablist" aria-label="Filter by actor">
                  {ACTORS.map((a) => (
                    <button key={a || 'all'} role="tab" aria-selected={actor === a} className={actor === a ? 'active' : ''}
                      onClick={() => setActor(a)}>
                      {a || 'All'}
                    </button>
                  ))}
                </div>
                <input className="search" type="search" placeholder="Search actions, IDs, details" aria-label="Search audit log"
                  value={query} onChange={(e) => setQuery(e.target.value)} />
              </div>
              <div className="toolbar">
                <span className="muted small">{rows.length} of {page.count} events</span>
                <button className="button" onClick={() => grid.current?.api.exportDataAsCsv({ fileName: exportName('audit') })}>
                  Export CSV
                </button>
              </div>
            </div>
            <div className="grid-frame">
              <AgGridReact<AuditRow>
                ref={grid}
                theme={ledgerTheme}
                rowData={rows}
                columnDefs={columns}
                defaultColDef={{ sortable: true, resizable: true, suppressHeaderMenuButton: true }}
                quickFilterText={query}
                getRowId={(p) => String(p.data.id)}
                pagination
                paginationPageSize={25}
                paginationPageSizeSelector={[25, 50, 100]}
                rowStyle={{ cursor: 'default' }}
              />
            </div>
          </>
        )}
      </Async>
    </>
  )
}

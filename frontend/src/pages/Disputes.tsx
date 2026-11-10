import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { AgGridReact } from 'ag-grid-react'
import type { CustomCellRendererProps } from 'ag-grid-react'
import type { ColDef } from 'ag-grid-community'
import { api } from '../api'
import type { DisputeRow } from '../api'
import { Async, PageHeader } from '../components'
import { dateTime, humanize, money, reasonLabel } from '../format'
import { ledgerTheme } from '../grid'
import { useLoad } from '../hooks'

function hoursUntil(iso: string | null): number | null {
  return iso ? (new Date(iso).getTime() - Date.now()) / 3_600_000 : null
}

function DeadlineCell(p: CustomCellRendererProps<DisputeRow>) {
  const d = p.data
  if (!d || d.status !== 'WAITING_FOR_SELLER_RESPONSE') return <span className="muted">—</span>
  const h = hoursUntil(d.seller_response_due_at)
  if (h === null) return <span className="muted">—</span>
  const text = h < 0 ? 'overdue' : h < 48 ? `${Math.floor(h)} h left` : `${Math.floor(h / 24)} days left`
  return <span className={`deadline ${h < 72 ? 'deadline-urgent' : ''}`}>{text}</span>
}

function CopilotCell(p: CustomCellRendererProps<DisputeRow>) {
  const d = p.data
  if (!d?.copilot) return <span className="muted small">not started</span>
  if (d.copilot.status === 'READY' && d.status === 'WAITING_FOR_SELLER_RESPONSE')
    return <span className="pill pill-partial">Ready · {humanize(d.copilot.recommendation)}</span>
  if (d.copilot.status === 'SUBMITTED') return <span className="pill pill-protected">Sent to PayPal</span>
  return <span className="pill pill-none">{humanize(d.copilot.status)}</span>
}

function ReasonCell(p: CustomCellRendererProps<DisputeRow>) {
  return (
    <span className="cell-two">
      <strong>{reasonLabel(p.data?.reason ?? '')}</strong>
      <small>{p.data?.paypal_dispute_id}</small>
    </span>
  )
}

export default function Disputes() {
  const navigate = useNavigate()
  const state = useLoad(() => api.disputes(), [])
  const columns = useMemo<ColDef<DisputeRow>[]>(() => [
    { headerName: 'Reason', field: 'reason', flex: 1.4, minWidth: 220, cellRenderer: ReasonCell,
      getQuickFilterText: (p) => reasonLabel(p.data?.reason ?? '') },
    { headerName: 'Buyer', field: 'buyer', flex: 1, minWidth: 140 },
    { headerName: 'Copilot', colId: 'copilot', width: 190, cellRenderer: CopilotCell,
      valueGetter: (p) => p.data?.copilot?.status ?? '' },
    { headerName: 'PayPal status', field: 'status', width: 200,
      valueFormatter: (p) => (p.data?.outcome ? humanize(p.data.outcome) : humanize(p.value ?? '')) },
    { headerName: 'Respond by', field: 'seller_response_due_at', width: 140, cellRenderer: DeadlineCell },
    { headerName: 'Opened', field: 'created_at', width: 140, sort: 'desc', valueFormatter: (p) => (p.value ? dateTime(p.value) : '') },
    { headerName: 'Amount', field: 'amount', width: 110, type: 'rightAligned', comparator: (a, b) => Number(a) - Number(b),
      valueFormatter: (p) => (p.data ? money(p.value, p.data.currency) : '') },
  ], [])

  return (
    <>
      <PageHeader eyebrow="Disputes" title="Disputes, with a copilot for each"
        subtitle="Evidence, a recommendation and a drafted reply for every dispute. Nothing is sent until you approve it." />
      <Async state={state}>
        {(page) => (
          <div className="grid-frame short">
            <AgGridReact<DisputeRow>
              theme={ledgerTheme}
              rowData={page.results}
              columnDefs={columns}
              defaultColDef={{ sortable: true, resizable: true, suppressHeaderMenuButton: true }}
              getRowId={(p) => String(p.data.id)}
              onRowClicked={(e) => e.data && navigate(`/disputes/${e.data.id}`)}
              overlayNoRowsTemplate="No disputes. Long may it last."
            />
          </div>
        )}
      </Async>
    </>
  )
}

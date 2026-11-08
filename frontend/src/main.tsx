import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import App from './App'
import './index.css'
import Audit from './pages/Audit'
import Dashboard from './pages/Dashboard'
import Disputes from './pages/Disputes'
import DisputeCopilot from './pages/DisputeCopilot'
import OrderDetail from './pages/OrderDetail'
import Orders from './pages/Orders'

// React Flow is the heaviest dependency; load the graph page on demand.
const Rings = lazy(() => import('./pages/Rings'))

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'orders', element: <Orders /> },
      { path: 'orders/:id', element: <OrderDetail /> },
      { path: 'rings', element: <Suspense fallback={<div className="skeleton" />}><Rings /></Suspense> },
      { path: 'disputes', element: <Disputes /> },
      { path: 'disputes/:id', element: <DisputeCopilot /> },
      { path: 'audit', element: <Audit /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
)

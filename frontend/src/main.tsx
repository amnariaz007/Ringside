import { lazy, StrictMode, Suspense } from 'react'
import type React from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import '@fontsource-variable/fraunces'
import '@fontsource-variable/inter'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import App from './App'
import { AuthProvider } from './auth'
import './index.css'
import Dashboard from './pages/Dashboard'
import DisputeCopilot from './pages/DisputeCopilot'
import OrderDetail from './pages/OrderDetail'

// Heavy pages load on demand: React Flow (graph) and AG Grid (tables).
const Rings = lazy(() => import('./pages/Rings'))
const Orders = lazy(() => import('./pages/Orders'))
const Disputes = lazy(() => import('./pages/Disputes'))
const Audit = lazy(() => import('./pages/Audit'))

const wait = (el: React.ReactNode) => <Suspense fallback={<div className="skeleton" />}>{el}</Suspense>

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'orders', element: wait(<Orders />) },
      { path: 'orders/:id', element: <OrderDetail /> },
      { path: 'rings', element: wait(<Rings />) },
      { path: 'disputes', element: wait(<Disputes />) },
      { path: 'disputes/:id', element: <DisputeCopilot /> },
      { path: 'audit', element: wait(<Audit />) },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  </StrictMode>,
)

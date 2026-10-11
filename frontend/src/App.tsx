import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { ApiProvider } from '@/api/ApiProvider'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Shell } from '@/components/workspace/Shell'
import { QUEUE_PATH, queueUrl } from '@/lib/routes'
import { ApprovalPage } from '@/pages/ApprovalPage'
import { NetstatsPage } from '@/pages/NetstatsPage'
import { NetworkPage } from '@/pages/NetworkPage'
import { ReceiptPage } from '@/pages/ReceiptPage'
import { RedTeamPage } from '@/pages/RedTeamPage'
import { SplashPage } from '@/pages/SplashPage'
import { TokensPage } from '@/pages/TokensPage'
import { TrustPage } from '@/pages/TrustPage'
import { WorkspacePage } from '@/pages/WorkspacePage'
import { PaymentsProvider } from '@/store/PaymentsProvider'
import { UiProvider } from '@/store/UiProvider'
import { ThemeProvider } from '@/theme/ThemeProvider'

function PaymentRedirect() {
  const { id = '' } = useParams()
  return <Navigate to={queueUrl(id)} replace />
}

/** Every routed screen. `/` is the splash; everything else renders inside the Shell. */
export function AppRoutes() {
  return (
    <Routes>
      <Route index element={<SplashPage />} />
      <Route element={<Shell />}>
        <Route path={QUEUE_PATH.slice(1)} element={<WorkspacePage />} />
        <Route path="approve" element={<ApprovalPage />} />
        <Route path="receipt/:id" element={<ReceiptPage />} />
        {/* The Fairness screen was cut; old links land on the queue. */}
        <Route path="fairness" element={<Navigate to={QUEUE_PATH} replace />} />
        <Route path="network" element={<NetworkPage />} />
        <Route path="netstats" element={<NetstatsPage />} />
        <Route path="redteam" element={<RedTeamPage />} />
        <Route path="trust" element={<TrustPage />} />
        <Route path="tokens" element={<TokensPage />} />
        <Route path="payments/:id" element={<PaymentRedirect />} />
        <Route path="*" element={<Navigate to={QUEUE_PATH} replace />} />
      </Route>
    </Routes>
  )
}

/** Everything the routes need except the router itself, so tests can mount a MemoryRouter. */
export function AppProviders({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <ApiProvider>
        <PaymentsProvider>
          <UiProvider>
            <TooltipProvider delayDuration={150}>
              {children}
              <Toaster />
            </TooltipProvider>
          </UiProvider>
        </PaymentsProvider>
      </ApiProvider>
    </ThemeProvider>
  )
}

export default function App() {
  return (
    <AppProviders>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AppProviders>
  )
}

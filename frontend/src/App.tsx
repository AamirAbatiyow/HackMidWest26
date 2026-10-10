import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { ApiProvider } from '@/api/ApiProvider'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Shell } from '@/components/workspace/Shell'
import { ApprovalPage } from '@/pages/ApprovalPage'
import { FairnessPage } from '@/pages/FairnessPage'
import { NetworkPage } from '@/pages/NetworkPage'
import { ReceiptPage } from '@/pages/ReceiptPage'
import { RedTeamPage } from '@/pages/RedTeamPage'
import { TokensPage } from '@/pages/TokensPage'
import { WorkspacePage } from '@/pages/WorkspacePage'
import { PaymentsProvider } from '@/store/PaymentsProvider'
import { UiProvider } from '@/store/UiProvider'
import { ThemeProvider } from '@/theme/ThemeProvider'

function PaymentRedirect() {
  const { id = '' } = useParams()
  return <Navigate to={`/?payment=${encodeURIComponent(id)}`} replace />
}

export default function App() {
  return (
    <ThemeProvider>
      <ApiProvider>
        <PaymentsProvider>
          <UiProvider>
            <TooltipProvider delayDuration={150}>
              <BrowserRouter>
                <Routes>
                  <Route element={<Shell />}>
                    <Route index element={<WorkspacePage />} />
                    <Route path="approve" element={<ApprovalPage />} />
                    <Route path="receipt/:id" element={<ReceiptPage />} />
                    <Route path="fairness" element={<FairnessPage />} />
                    <Route path="network" element={<NetworkPage />} />
                    <Route path="redteam" element={<RedTeamPage />} />
                    <Route path="tokens" element={<TokensPage />} />
                    <Route path="payments/:id" element={<PaymentRedirect />} />
                    <Route path="*" element={<Navigate to="/" replace />} />
                  </Route>
                </Routes>
              </BrowserRouter>
              <Toaster />
            </TooltipProvider>
          </UiProvider>
        </PaymentsProvider>
      </ApiProvider>
    </ThemeProvider>
  )
}

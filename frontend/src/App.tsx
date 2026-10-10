import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ApiProvider } from '@/api/ApiProvider'
import { AppShell } from '@/components/layout/AppShell'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { ApprovalPage } from '@/pages/ApprovalPage'
import { FairnessPage } from '@/pages/FairnessPage'
import { NetworkPage } from '@/pages/NetworkPage'
import { PayablesDesk } from '@/pages/PayablesDesk'
import { ReceiptPage } from '@/pages/ReceiptPage'
import { RedTeamPage } from '@/pages/RedTeamPage'
import { TokensPage } from '@/pages/TokensPage'
import { PaymentsProvider } from '@/store/PaymentsProvider'
import { UiProvider } from '@/store/UiProvider'
import { ThemeProvider } from '@/theme/ThemeProvider'

export default function App() {
  return (
    <ThemeProvider>
      <ApiProvider>
        <PaymentsProvider>
          <UiProvider>
            <TooltipProvider delayDuration={200}>
              <BrowserRouter>
                <Routes>
                  <Route element={<AppShell />}>
                    <Route index element={<PayablesDesk />} />
                    <Route path="payments/:id" element={<PaymentRedirect />} />
                    <Route path="approve" element={<ApprovalPage />} />
                    <Route path="receipt/:batchId" element={<ReceiptPage />} />
                    <Route path="fairness" element={<FairnessPage />} />
                    <Route path="network" element={<NetworkPage />} />
                    <Route path="redteam" element={<RedTeamPage />} />
                    <Route path="tokens" element={<TokensPage />} />
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

import { useParams } from 'react-router-dom'

function PaymentRedirect() {
  const { id = '' } = useParams()
  return <Navigate to={`/?payment=${encodeURIComponent(id)}`} replace />
}

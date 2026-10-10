import { Toaster as Sonner, type ToasterProps } from 'sonner'
import { CircleCheckIcon, InfoIcon, TriangleAlertIcon, OctagonXIcon, Loader2Icon } from 'lucide-react'
import { useTheme } from '@/theme/ThemeProvider'

const Toaster = ({ ...props }: ToasterProps) => {
  const { theme } = useTheme()

  return (
    <Sonner
      theme={theme}
      className="toaster group"
      position="bottom-right"
      icons={{
        success: <CircleCheckIcon className="size-4 text-vouched" />,
        info: <InfoIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4 text-attention" />,
        error: <OctagonXIcon className="size-4 text-problem" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      style={
        {
          '--normal-bg': 'var(--popover)',
          '--normal-text': 'var(--popover-foreground)',
          '--normal-border': 'var(--border)',
          '--border-radius': 'var(--radius-xl)',
        } as React.CSSProperties
      }
      toastOptions={{
        classNames: {
          toast: 'cn-toast shadow-card-hover! font-sans!',
        },
      }}
      {...props}
    />
  )
}

export { Toaster }

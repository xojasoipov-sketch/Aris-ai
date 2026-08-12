import { AppShell } from "@/components/shell/AppShell";
import { FloatingAssistant } from "@/components/widget/FloatingAssistant";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppShell>
      {children}
      <FloatingAssistant />
    </AppShell>
  );
}

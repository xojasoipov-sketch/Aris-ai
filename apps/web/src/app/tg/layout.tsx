import Script from "next/script";

/** Telegram Mini App layout — AppShell YO'Q (bir ustunli, 100vw).
 * telegram-web-app.js rasmiy SDK skripti — WebApp.initData/theme_params.
 */
export default function TgLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Script src="https://telegram.org/js/telegram-web-app.js" strategy="beforeInteractive" />
      {children}
    </>
  );
}

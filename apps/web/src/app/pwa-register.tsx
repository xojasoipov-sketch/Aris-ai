"use client";

/* ZET PWA registratsiyasi.
 *
 * Service worker'ni faqat brauzerda va faqat production build'da
 * ro'yxatga oladi — dev'da /_next/webpack-hmr bilan konflikt bo'lmaydi.
 * SSR paytida bu komponent hech qanday DOM ishlab chiqarmaydi.
 */

import { useEffect } from "react";

export default function PwaRegister(): null {
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (process.env.NODE_ENV !== "production") return;
    if (!("serviceWorker" in navigator)) return;

    const register = () => {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {
        // Sekin fail — foydalanuvchi tajribasini buzmaydi.
      });
    };

    if (document.readyState === "complete") {
      register();
    } else {
      window.addEventListener("load", register, { once: true });
    }
  }, []);

  return null;
}

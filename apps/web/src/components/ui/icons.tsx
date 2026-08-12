/** Chiziqli ikonlar — docs/10 §2: yupqa chiziq (1.5px), yumaloq uchlar, monoxrom.
 * Rang currentColor orqali — konteyner belgilaydi.
 */

import type { SVGProps } from "react";

function Icon({ children, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      {children}
    </svg>
  );
}

export const IconDashboard = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <rect x="3" y="3" width="7" height="9" rx="1.5" />
    <rect x="14" y="3" width="7" height="5" rx="1.5" />
    <rect x="14" y="12" width="7" height="9" rx="1.5" />
    <rect x="3" y="16" width="7" height="5" rx="1.5" />
  </Icon>
);

export const IconAssistant = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="8" strokeDasharray="2 3" />
    <circle cx="12" cy="12" r="3" />
  </Icon>
);

export const IconAgents = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <circle cx="9" cy="8" r="3.5" />
    <path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6" />
    <circle cx="17" cy="7" r="2.5" />
    <path d="M15.5 13.5c2.8.3 5 2.7 5 5.5" />
  </Icon>
);

export const IconProjects = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
  </Icon>
);

export const IconCalendar = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <rect x="3" y="5" width="18" height="16" rx="2" />
    <path d="M3 10h18M8 3v4M16 3v4" />
  </Icon>
);

export const IconTasks = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M9 6h11M9 12h11M9 18h11" />
    <path d="M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2" />
  </Icon>
);

export const IconMessages = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M21 12a8 8 0 0 1-8 8H4l2-3a8 8 0 1 1 15-5z" />
  </Icon>
);

export const IconFiles = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M6 2h8l5 5v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z" />
    <path d="M14 2v5h5" />
  </Icon>
);

export const IconAnalytics = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M4 20V10M10 20V4M16 20v-7M21 20H3" />
  </Icon>
);

export const IconDevices = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <rect x="2" y="4" width="14" height="10" rx="1.5" />
    <path d="M6 18h6M9 14v4" />
    <rect x="17" y="8" width="5" height="10" rx="1.5" />
  </Icon>
);

export const IconCamera = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M3 8a2 2 0 0 1 2-2h2l2-2h6l2 2h2a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8z" />
    <circle cx="12" cy="13" r="3.5" />
  </Icon>
);

export const IconSettings = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1" />
  </Icon>
);

export const IconMic = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
  </Icon>
);

export const IconSend = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z" />
  </Icon>
);

export const IconBell = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
    <path d="M10.3 21a2 2 0 0 0 3.4 0" />
  </Icon>
);

export const IconSearch = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </Icon>
);

export const IconRefresh = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M21 12a9 9 0 1 1-2.6-6.4M21 3v6h-6" />
  </Icon>
);

export const IconVolume = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M11 5 6 9H2v6h4l5 4V5z" />
    <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" />
  </Icon>
);

export const IconVolumeOff = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M11 5 6 9H2v6h4l5 4V5z" />
    <path d="m16 9 6 6M22 9l-6 6" />
  </Icon>
);

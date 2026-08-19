import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Tarang Clinical Workstation',
  description: 'Precision ICU Cardiac Telemetry Workstation & Real-Time Monitor',
  icons: {
    icon: '/tarang_logo.png',
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

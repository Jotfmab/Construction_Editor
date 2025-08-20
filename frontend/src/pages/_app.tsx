// frontend/pages/_app.tsx
import type { AppProps } from "next/app";

// ✅ AG Grid styles (must be imported once at app level)
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";

// (optional) your global styles
import "../../styles/globals.css";

export default function MyApp({ Component, pageProps }: AppProps) {
  return <Component {...pageProps} />;
}

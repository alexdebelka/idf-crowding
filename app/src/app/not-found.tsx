import Link from "next/link";

export default function NotFound() {
  return (
    <div className="screen ground-papier" style={{ padding: "var(--pad-top) var(--pad-x)" }}>
      <h1 style={{ fontSize: 54, fontWeight: 800, letterSpacing: "-0.04em", lineHeight: 0.98 }}>
        Gare introuvable.
      </h1>
      <p lang="en" style={{ marginTop: 12, fontWeight: 600 }}>
        Station not found.
      </p>
      <p style={{ marginTop: 24 }}>
        <Link href="/" className="pill">
          Toutes les gares · All stations
        </Link>
      </p>
    </div>
  );
}

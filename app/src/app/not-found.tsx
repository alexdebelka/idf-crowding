import Link from "next/link";

export default function NotFound() {
  return (
    <section className="hero">
      <h1>Station introuvable · Station not found</h1>
      <p>
        <Link href="/">← Gares · Stations</Link>
      </p>
    </section>
  );
}

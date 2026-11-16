import type { Metadata } from "next";
import { About } from "@/components/About";
import { getIndex } from "@/lib/data";

export const metadata: Metadata = { title: "Méthode et données" };

export default function AboutPage() {
  const index = getIndex();
  return <About period={index.data_period} attribution={index.attribution} />;
}

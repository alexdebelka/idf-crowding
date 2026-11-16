import type { Metadata } from "next";
import { PlaceView } from "@/components/PlaceView";
import { getIndex, getPlace } from "@/lib/data";

export const dynamicParams = false;

export function generateStaticParams() {
  return getIndex().places.map((p) => ({ id: p.id }));
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  const p = getPlace(id).place;
  return {
    title: p.name,
    description: `Affluence heure par heure à ${p.name}${p.town ? ` (${p.town})` : ""} : quand partir pour éviter la foule.`,
  };
}

export default async function PlacePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <PlaceView data={getPlace(id)} />;
}

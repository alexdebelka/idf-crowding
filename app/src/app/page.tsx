import { Hero } from "@/components/Hero";
import { Search } from "@/components/Search";
import { getIndex } from "@/lib/data";

export default function Home() {
  const index = getIndex();
  return (
    <>
      <Hero count={index.places.length} />
      <Search places={index.places} />
    </>
  );
}

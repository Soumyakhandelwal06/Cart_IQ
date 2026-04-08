export default function SearchSkeleton({ scraping }: { scraping: boolean }) {
  return (
    <div className="max-w-6xl mx-auto mt-6">
      {scraping && (
        <div className="flex justify-center gap-6 mb-8">
          {["Blinkit", "Zepto", "Bigbasket"].map((name) => (
            <div key={name} className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-violet-500 animate-pulse shadow-sm shadow-violet-500/50" />
              <span className="text-slate-500 font-medium text-sm">Searching {name}...</span>
            </div>
          ))}
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {[1, 2, 3].map((i) => (
          <div key={i} className="rounded-3xl bg-white border border-slate-200 shadow-xl shadow-slate-200/40 overflow-hidden">
            {/* Header skeleton */}
            <div className="px-6 py-5 border-b border-slate-100 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-full skeleton" />
                <div className="w-24 h-6 rounded skeleton" />
              </div>
              <div className="w-16 h-5 rounded skeleton" />
            </div>
            {/* Item skeletons */}
            <div className="px-6 py-4 space-y-4 h-[350px]">
              {[1, 2, 3, 4].map((j) => (
                <div key={j} className="flex justify-between items-center py-2">
                  <div className="flex gap-4 items-center w-full">
                    <div className="w-14 h-14 rounded-xl skeleton flex-shrink-0" />
                    <div className="w-full space-y-2">
                      <div className="w-3/4 h-4 rounded skeleton" />
                      <div className="w-1/2 h-3 rounded skeleton" />
                    </div>
                  </div>
                  <div className="w-16 h-5 rounded skeleton flex-shrink-0 ml-4" />
                </div>
              ))}
            </div>
            {/* Fee area skeleton */}
            <div className="px-6 py-4 bg-slate-50 space-y-3 border-t border-slate-100">
              {[1, 2].map((k) => (
                <div key={k} className="flex justify-between">
                  <div className="w-24 h-3 rounded skeleton" />
                  <div className="w-12 h-3 rounded skeleton" />
                </div>
              ))}
              <div className="border-t border-slate-200/60 pt-3 mt-1 flex justify-between items-end">
                <div className="w-20 h-4 rounded skeleton" />
                <div className="w-24 h-8 rounded skeleton" />
              </div>
            </div>
            {/* Button skeleton */}
            <div className="px-6 py-5">
              <div className="w-full h-14 rounded-2xl skeleton" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}


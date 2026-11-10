# ADR-0001: Geçmişi koruyan bağımsız başlangıç

Tarih: 2026-11-10. Karar: `aegisflow-data-reliability` adlı yeni özel depo.

Eski `aegisflow-ai-labs/Aegisflow-ai` deposu tedarik/SLA odaklı deterministik prototip, API, erişim denetimi ve testler içerir. Yeni veri hattı güvenilirliği kapsamıyla aynı ürün tabanı olarak sunulmayacaktır.

Eski depo yeniden adlandırılmayacak, arşivlenmeyecek, geçmişi yeniden yazılmayacaktır. Önceki ChatGPT konuşmaları ve AegisFlow_AI proje alanı korunacaktır. Gerekirse ileride ayrı onayla arşivleme yapılabilir.

Yeni depo eski kodun kopyası değildir. Mimari yanıtın tamamını, özgün diagramları ve kaynak kökenini içerir. Eski rol kimliklerinin anlamları yeni katalogla karıştırılmamalıdır.

Adlandırma: Ürün AegisFlow AI; alan Agentic Data Reliability; depo aegisflow-data-reliability; Python paketi aegisflow_dr.

# Altı katman ve kaynak sahipliği

L1: apps/web — araştırma arayüzü (planlandı).
L2: src/aegisflow_dr/integration — bağlayıcı ve telemetri (planlandı).
L3: src/aegisflow_dr/diagnostics — deterministik kalite ve teşhis (planlandı).
L4: src/aegisflow_dr/orchestration — araç geçidi, registry ve yürütme (yalnız katalog doğrulaması mevcut).
L5: src/aegisflow_dr/workflow — kanıt, onarım, sandbox ve insan onayı (planlandı).
L6: infrastructure — erişim politikası, izleme, değerlendirme ve dağıtım (planlandı).

36 rollerin hepsi için özgün görev ve etkinleşme tanımları agent-catalog.json içindedir. Bunlar yürütülebilir sözleşme değildir; input/output şemaları ve araç izinleri geliştirme aşamasında tamamlanacaktır.

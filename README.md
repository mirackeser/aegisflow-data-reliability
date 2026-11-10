# AegisFlow AI — Agentic Data Reliability

ETL/ELT veri hatlarında kalite hatalarını araştıran, kanıtlı kök neden ve kontrollü düzeltme önerisi hedefleyen araştırma projesi.

## Durum

Yeni ve bağımsız başlangıç iskeleti. 36 uzman rolü **planlanmıştır**; ajan yürütme motoru henüz uygulanmamıştır. Çalışan eski tedarik/SLA prototipi ayrı depoda korunur: https://github.com/aegisflow-ai-labs/Aegisflow-ai

## Belgeler

- [Eksiksiz mimari PDF](docs/AegisFlow-AI-Mimari-v1.0.pdf)
- [Mimari metin](docs/architecture.md)
- [36 rol kataloğu](docs/agent-catalog.json)
- [Özgün Mermaid ve SVG şemaları](docs/diagrams/)
- [Geçmiş koruma kararı](docs/adr/0001-clean-restart.md)
- [Kaynak kökeni](docs/source/provenance.json)

## Yerel kontrol

Python 3.11+ ile bağımlılık gerektirmeden:

```sh
python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m aegisflow_dr
```

İkinci komut rol kataloğunu doğrular; bir AI araştırması çalıştırmaz.

## İlk geliştirme sırası

Sentetik e-ticaret verisi → batch SQL/Python veri hattı → hata enjeksiyonu → deterministik kalite/teşhis araçları → izin ve bütçe kontrollü araç geçidi → dinamik ajan yürütme → kanıt doğrulama → sandbox ve insan incelemesi.

Üretim verisi değiştirilmez. İlk kurumsal pilot salt okunur ve yetkilendirilmiş olacaktır. Yol haritası, deney sayıları ve ajan öncelikleri mimari belgedeki tasarım hedefleridir; ölçülmüş başarı değildir.

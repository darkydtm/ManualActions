[English](README-en.md) | [Русский](README.md)
# Быстрый старт
1. Соберите плагин
```python
python3 build_plugin.py
```
2. Установите плагин manual_actions.py в папке dist/ в Cardinal

## 2FA-коды

Добавьте в описание заказа строку `2FA: <секрет TOTP>` - метка меняется в настройках плагина. После создания заказа любой участник чата может получить код командами `!code` или `!code <номер заказа>`.

<details>
<summary>Скриншоты</summary>
<img width="568" height="330" alt="изображение" src="https://github.com/user-attachments/assets/acd1389c-c7a4-4727-9d86-ec8a625acc73" />
<img width="739" height="718" alt="изображение" src="https://github.com/user-attachments/assets/61626577-0755-4af4-af34-631f00a3ecd8" />

</details>

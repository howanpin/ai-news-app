# 1. 公式のPythonイメージ
FROM python:3.12

# 2. コンテナ内の作業ディレクトリを設定
WORKDIR /app

# 3. 手元の「app.py」をコンテナ内の「/app」にコピー
COPY app.py .

# 4. コンテナ起動時に実行するコマンドを指定
CMD ["python", "app.py"]
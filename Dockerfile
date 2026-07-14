# 公式のPythonイメージ
FROM python:3.12

# コンテナ内の作業ディレクトリを設定
WORKDIR /app

# 手元の「app.py」をコンテナ内の「/app」にコピー
COPY app.py .

# コンテナ起動時に実行するコマンドを指定
CMD ["python", "app.py"]
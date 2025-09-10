import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from fpdf import FPDF
import io
import pdfplumber
import re
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader

# --------------------------- LOGIN ---------------------------
with open("config.yaml") as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days'],
    config['preauthorized']
)

name, authentication_status, username = authenticator.login("main")

if authentication_status == False:
    st.error("❌ Usuario o contraseña incorrectos")
elif authentication_status == None:
    st.warning("⚠️ Ingresa tus credenciales")
elif authentication_status:

    # --------------------------- Configuración página ---------------------------
    st.set_page_config(
        page_title="Hernaninho",
        page_icon="💼",
        layout="wide"
    )

    st.title("💼 Hernaninho")
    st.markdown("Dashboard inteligente con gráficos detallados y resúmenes diarios, quincenales y mensuales.")

    # --------------------------- Subida de archivo ---------------------------
    archivo = st.file_uploader("📁 Sube archivo Excel, CSV o PDF", type=["csv","xlsx","pdf"])

    if archivo:
        try:
            # --------- Leer archivo ---------
            if archivo.name.endswith(".csv"):
                df = pd.read_csv(archivo)
            elif archivo.name.endswith(".xlsx"):
                df = pd.read_excel(archivo)
            else:  # PDF
                with pdfplumber.open(archivo) as pdf:
                    tables = []
                    for page in pdf.pages:
                        for table in page.extract_tables():
                            tables.append(pd.DataFrame(table[1:], columns=table[0]))
                    if tables:
                        df = pd.concat(tables, ignore_index=True)
                    else:
                        st.error("❌ No se encontraron tablas en el PDF")
                        df = pd.DataFrame()

            if df.empty:
                st.error("❌ El archivo no contiene datos")
            else:
                # --------- Detectar columna de fecha automáticamente ---------
                fecha_col = None
                for col in df.columns:
                    try:
                        sample_dates = pd.to_datetime(df[col], errors='coerce', dayfirst=True)
                        if sample_dates.notna().sum() / len(sample_dates) > 0.5:
                            fecha_col = col
                            df['fecha'] = sample_dates
                            break
                    except:
                        continue

                if fecha_col is None:
                    fecha_col = st.selectbox("Selecciona la columna que contiene la fecha", df.columns)
                    df['fecha'] = pd.to_datetime(df[fecha_col], errors='coerce', dayfirst=True)

                df = df.dropna(subset=['fecha'])

                # --------- Detectar columna de valor automáticamente ---------
                valor_col = None
                for col in df.columns:
                    if col == 'fecha':
                        continue
                    sample = df[col].astype(str).str.replace(r'[^\d.-]', '', regex=True)
                    sample = pd.to_numeric(sample, errors='coerce')
                    if sample.notna().sum() / len(sample) > 0.6:
                        valor_col = col
                        df['valor'] = sample
                        break
                if valor_col is None:
                    valor_col = st.selectbox("Selecciona la columna que contiene los montos/valores", df.columns)
                    df['valor'] = pd.to_numeric(df[valor_col].astype(str).str.replace(r'[^\d.-]', '', regex=True), errors='coerce')

                # --------- Detectar columnas opcionales ---------
                tipo_col, desc_col, num_col = None, None, None
                for col in df.columns:
                    low = col.lower()
                    if any(x in low for x in ['tipo','movimiento','operacion']):
                        tipo_col = col
                    if any(x in low for x in ['descripcion','detalle','concepto','nombre','remitente']):
                        desc_col = col
                    if any(x in low for x in ['numero','cuenta','transferencia']):
                        num_col = col

                if tipo_col: df.rename(columns={tipo_col:'tipo'}, inplace=True)
                if desc_col: df.rename(columns={desc_col:'descripcion'}, inplace=True)
                if num_col: df.rename(columns={num_col:'numero_transferencia'}, inplace=True)

                # --------- Detectar ingreso/egreso automáticamente ---------
                if 'tipo' not in df.columns:
                    df['tipo'] = df['valor'].apply(lambda x: 'egreso' if x < 0 else 'ingreso')
                    df['valor'] = df['valor'].abs()

                # --------- Detectar remitente automáticamente ---------
                if 'descripcion' in df.columns:
                    df['remitente'] = df['descripcion'].apply(lambda x: re.findall(r'\b[A-Z][a-z]+\s[A-Z][a-z]+\b', str(x))[0] if re.findall(r'\b[A-Z][a-z]+\s[A-Z][a-z]+\b', str(x)) else '')

                # --------- Filtros ---------
                st.sidebar.header("Filtros")
                fecha_inicio = st.sidebar.date_input("Fecha inicio", df['fecha'].min().date())
                fecha_fin = st.sidebar.date_input("Fecha fin", df['fecha'].max().date())
                fecha_inicio_dt = datetime.combine(fecha_inicio, datetime.min.time())
                fecha_fin_dt = datetime.combine(fecha_fin, datetime.max.time())
                df_filtrado = df[(df['fecha'] >= fecha_inicio_dt) & (df['fecha'] <= fecha_fin_dt)]

                ingresos = df_filtrado[df_filtrado['tipo']=='ingreso']['valor'].sum()
                egresos = df_filtrado[df_filtrado['tipo']=='egreso']['valor'].sum()
                balance = ingresos - egresos

                st.subheader("📌 Resumen General")
                c1,c2,c3 = st.columns(3)
                c1.metric("💰 Ingresos", f"${ingresos:,.2f}")
                c2.metric("💸 Egresos", f"${egresos:,.2f}")
                c3.metric("⚖️ Balance", f"${balance:,.2f}")

                df_filtrado['mes'] = df_filtrado['fecha'].dt.to_period('M')
                df_filtrado['quincena'] = df_filtrado['fecha'].dt.day.apply(lambda x: 1 if x<=15 else 2)

                # --------- Tabs ---------
                tab1, tab2, tab3, tab4 = st.tabs([
                    "📊 Gráficos Detallados",
                    "🗓 Resúmenes",
                    "📄 PDF Hernaninho",
                    "💾 Excel"
                ])

                # --------- Tab 1: Gráficos ---------
                with tab1:
                    hover_cols = [col for col in ['descripcion','remitente','numero_transferencia'] if col in df_filtrado.columns]
                    fig_bar = px.bar(
                        df_filtrado,
                        x='fecha',
                        y='valor',
                        color='tipo',
                        hover_data=hover_cols,
                        text='valor',
                        color_discrete_map={'ingreso':'#4CAF50','egreso':'#F44336'},
                        title="Ingresos vs Egresos Detallado"
                    )
                    st.plotly_chart(fig_bar, use_container_width=True)

                    if 'descripcion' in df_filtrado.columns:
                        egresos_detalle = df_filtrado[df_filtrado['tipo']=='egreso'].groupby('descripcion')['valor'].sum().reset_index()
                        fig_pie = px.pie(egresos_detalle, names='descripcion', values='valor', title="Distribución de Egresos")
                        st.plotly_chart(fig_pie, use_container_width=True)

                # --------- Tab 2: Resúmenes ---------
                with tab2:
                    st.subheader("Resumen Diario")
                    resumen_diario = df_filtrado.groupby(['fecha','tipo'])['valor'].sum().unstack(fill_value=0)
                    st.dataframe(resumen_diario)

                    st.subheader("Resumen Quincenal")
                    resumen_quincenal = df_filtrado.groupby(['mes','quincena','tipo'])['valor'].sum().unstack(fill_value=0)
                    st.dataframe(resumen_quincenal)

                    st.subheader("Resumen Mensual")
                    resumen_mensual = df_filtrado.groupby(['mes','tipo'])['valor'].sum().unstack(fill_value=0)
                    st.dataframe(resumen_mensual)

                # --------- Tab 3: PDF ---------
                with tab3:
                    if st.button("Exportar PDF"):
                        pdf = FPDF()
                        pdf.add_page()
                        pdf.set_font("Arial",'B',16)
                        pdf.cell(0,10,"Resumen Financiero Hernaninho",ln=True,align='C')
                        pdf.ln(10)
                        pdf.set_font("Arial",'',12)
                        pdf.cell(0,10,f"Ingresos: ${ingresos:,.2f}",ln=True)
                        pdf.cell(0,10,f"Egresos: ${egresos:,.2f}",ln=True)
                        pdf.cell(0,10,f"Balance: ${balance:,.2f}",ln=True)
                        pdf.ln(10)
                        for idx,row in df_filtrado.iterrows():
                            line = f"{row['fecha'].date()} | {row.get('descripcion','')} | {row.get('remitente','')} | {row.get('numero_transferencia','')} | ${row['valor']:,.2f}"
                            pdf.cell(0,8,line,ln=True)
                        pdf.output("resumen_financiero_hernaninho.pdf")
                        st.success("✅ PDF generado correctamente")

                # --------- Tab 4: Excel ---------
                with tab4:
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                        df_filtrado.to_excel(writer, index=False, sheet_name='Datos Filtrados')
                        resumen_diario.to_excel(writer, sheet_name='Resumen Diario')
                        resumen_quincenal.to_excel(writer, sheet_name='Resumen Quincenal')
                        resumen_mensual.to_excel(writer, sheet_name='Resumen Mensual')
                    st.download_button(
                        label="📥 Descargar Excel",
                        data=output.getvalue(),
                        file_name="resumen_financiero_hernaninho.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )

        except Exception as e:
            st.error(f"Error al procesar el archivo: {e}")

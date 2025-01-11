import streamlit as st
import os
import pandas as pd
import statistics
import io

from pointGeneratorUnif import PointGeneratorUnif
from grid import Grid
from kNN import kNN  # kNN.knn() -> (results, stats_str)
from linearScan import LinearScan  # ls.knn() -> (results, stats_str)
from spatialJoinPBSM import SpatialJoinPBSM  # pbsmsj.execute_join() -> (results, stats_str)
from naiveSpatialJoin import NaiveSpatialJoin  # naive_sj.execute_join() -> (results, stats_str)
from skyline_query import SkylineQuery  # sq.sky_query() -> (results, stats_str)

import folium
from streamlit_folium import st_folium

# ------------------------------------------------------
# Βοηθητικές Συναρτήσεις για αποθήκευση και εμφάνιση
# ------------------------------------------------------

def save_results(results, algorithm_name, stats=None):
    """
    Αποθήκευση αποτελεσμάτων + (προαιρετικά) στατιστικών σε αρχείο .txt,
    με τη βοήθεια download_button. Δεν αφήνει φυσικό αρχείο στον δίσκο,
    είναι in-memory (StringIO).
    """
    if not results:
        st.warning(f"Δεν υπάρχουν αποτελέσματα για αποθήκευση στον {algorithm_name}.")
        return

    st.info(f"Αποθήκευση αποτελεσμάτων {algorithm_name} σε τοπικό αρχείο (.txt):")

    output = io.StringIO()

    # 1. Αν υπάρχουν στατιστικά, τα γράφουμε πρώτα
    if stats:
        output.write(stats)
        output.write("\n")

    # 2. Γράφουμε επικεφαλίδες
    if algorithm_name in ['PBSM', 'Naive']:
        output.write("Dataset_A_ID\tDataset_B_ID\n")
    elif algorithm_name in ['k-NN', 'Linear Scan']:
        output.write("Dataset_ID\tDistance\n")
    elif algorithm_name == 'Skyline':
        output.write("Skyline Points (ID, xmin, ymin, xmax, ymax):\n")

    # 3. Γράφουμε τα αποτελέσματα
    for pair in results:
        if algorithm_name in ['PBSM', 'Naive']:
            a, b = pair
            output.write(f"{a.id}\t{b.id}\n")
        elif algorithm_name in ['k-NN', 'Linear Scan']:
            dist, obj = pair
            output.write(f"{obj.id}\t{dist:.4f}\n")
        elif algorithm_name == 'Skyline':
            obj = pair
            output.write(f"{obj.id}, {obj.xmin}, {obj.ymin}, {obj.xmax}, {obj.ymax}\n")

    data_str = output.getvalue()
    output.close()

    default_filename = f"results_{algorithm_name}.txt"

    st.download_button(
        label="Κατέβασε το αρχείο αποτελεσμάτων",
        data=data_str,
        file_name=default_filename,
        mime="text/plain"
    )

def display_map(all_points, skyline_points=None):
    """
    Δημιουργεί κι εμφανίζει έναν Folium χάρτη μέσα σε Streamlit,
    με markers για όλα τα σημεία (μπλε) και τα Skyline (κόκκινο).
    Υποθέτουμε xmin=lon, ymin=lat.
    """
    if not all_points:
        st.info("Δεν υπάρχουν δεδομένα για εμφάνιση στον χάρτη.")
        return

    lats = [p.ymin for p in all_points]
    lons = [p.xmin for p in all_points]
    center_lat = statistics.mean(lats)
    center_lon = statistics.mean(lons)

    folium_map = folium.Map(location=[center_lat, center_lon], zoom_start=12)

    # Μπλε markers = all_points
    for p in all_points:
        lat = p.ymin
        lon = p.xmin
        popup_text = f"ID: {p.id}"
        folium.Marker(
            [lat, lon],
            popup=popup_text,
            icon=folium.Icon(color='blue', icon='info-sign')
        ).add_to(folium_map)

    # Κόκκινα markers = skyline_points
    if skyline_points:
        for sp in skyline_points:
            lat = sp.ymin
            lon = sp.xmin
            popup_text = f"Skyline ID: {sp.id}"
            folium.Marker(
                [lat, lon],
                popup=popup_text,
                icon=folium.Icon(color='red', icon='star')
            ).add_to(folium_map)

    st_folium(folium_map, width=700, height=500)

# ------------------------------------------------------
# Κύρια λογική της εφαρμογής (Streamlit)
# ------------------------------------------------------
def main():
    st.title("Spatial Data Processing with Streamlit (Robust Temporary File Deletion)")
    st.write("""
    Εδώ εκτελούμε αλγορίθμους (Linear Scan, k-NN, PBSM, Naive Join, Skyline)
    και εμφανίζουμε/αποθηκεύουμε τα αποτελέσματα **μαζί με** τα στατιστικά τους!
    """)

    # -- Δημιουργία / επιλογή του Grid --
    with st.sidebar:
        st.header("Grid Settings")
        xL = st.number_input("xL", value=0.0)
        yL = st.number_input("yL", value=0.0)
        xU = st.number_input("xU", value=100.0)
        yU = st.number_input("yU", value=100.0)
        m = st.number_input("m (διαμερίσεις)", min_value=1, value=10)
        if st.button("Create/Reset Grid"):
            st.session_state["grid"] = Grid(xL, yL, xU, yU, m)
            st.success(f"Δημιουργήθηκε νέο Grid με m={m} [{xL},{yL}] - [{xU},{yU}]")

    if "grid" not in st.session_state:
        st.session_state["grid"] = Grid(0, 0, 100, 100, 10)

    grid = st.session_state["grid"]

    st.write("## Επιλογές Ενεργειών")
    menu = [
        "1. Δημιουργία Αρχείου Δεδομένων (PointGeneratorUnif)",
        "2. Εκτέλεση Linear Scan (Γραμμική Σάρωση)",
        "3. Εκτέλεση k-NN Αναζήτησης με Grid",
        "4. Εκτέλεση Spatial Join με PBSM",
        "5. Εκτέλεση Naive Spatial Join",
        "6. Εκτέλεση Skyline Query με Grid"
    ]
    choice = st.selectbox("Επίλεξε ενέργεια:", menu)

    # ------------------------------------
    # 1. Δημιουργία Αρχείου Δεδομένων
    # ------------------------------------
    if choice == menu[0]:
        st.subheader("Δημιουργία Αρχείου Δεδομένων")
        filename = st.text_input("Δώσε όνομα αρχείου (π.χ., data1.csv)", "data1.csv")
        num_rect = st.number_input("Αριθμός ορθογωνίων:", min_value=1, value=10)
        dataset_label = st.selectbox("Label dataset", ["A", "B", "default"])
        if st.button("Δημιουργία"):
            generator = PointGeneratorUnif(filename, grid.xL, grid.yL, grid.xU, grid.yU)
            try:
                generator.generate_rectangles(num_rect, include_id=True, dataset_label=dataset_label)
                st.success(f"Δημιουργήθηκε το αρχείο {filename} με {num_rect} ορθογώνια.")
            except Exception as e:
                st.error(f"Σφάλμα: {e}")

    # ------------------------------------
    # 2. Linear Scan
    # ------------------------------------
    elif choice == menu[1]:
        st.subheader("Εκτέλεση Linear Scan k-NN")
        uploaded_file = st.file_uploader("Φόρτωσε CSV (ID,xmin,ymin,xmax,ymax)", type="csv")
        if uploaded_file:
            temp_file = "temp_linear.csv"
            with open(temp_file, "wb") as f:
                f.write(uploaded_file.getbuffer())
            st.success(f"Το αρχείο ανέβηκε ως {temp_file}.")

            qx = st.number_input("x (query)", value=10.0)
            qy = st.number_input("y (query)", value=10.0)
            k = st.number_input("k (κοντινότεροι γείτονες)", min_value=1, value=3)

            if st.button("Εκτέλεση Linear Scan"):
                try:
                    ls = LinearScan(temp_file)
                    # Τώρα η linearScan.knn() επιστρέφει (results, stats_str)
                    results, lscan_stats = ls.knn(qx, qy, k)

                    st.write(f"Βρέθηκαν {len(results)} κοντινότεροι γείτονες:")
                    st.write(lscan_stats)  # Εμφανίζουμε τα στατιστικά στο UI

                    for dist, obj in results:
                        st.write(f"{obj} - dist={dist:.4f}")

                    # Αποθήκευση στο αρχείο (μαζί με stats)
                    save_results(results, "Linear Scan", stats=lscan_stats)

                finally:
                    try:
                        os.remove(temp_file)
                        st.info(f"Διαγράφηκε προσωρινό αρχείο '{temp_file}'.")
                    except FileNotFoundError:
                        pass
        else:
            st.info("Φόρτωσε ένα CSV για να κάνουμε Linear Scan.")

    # ------------------------------------
    # 3. k-NN με Grid
    # ------------------------------------
    elif choice == menu[2]:
        st.subheader("Εκτέλεση k-NN με Grid")
        uploaded_file = st.file_uploader("Φόρτωσε CSV (ID,xmin,ymin,xmax,ymax)", type="csv")

        if uploaded_file:
            temp_file = "temp_knn.csv"
            with open(temp_file, "wb") as f:
                f.write(uploaded_file.getbuffer())
            st.success(f"Το αρχείο ανέβηκε ως {temp_file}.")

            qx = st.number_input("x (query)", value=10.0)
            qy = st.number_input("y (query)", value=10.0)
            k = st.number_input("k γείτονες:", min_value=1, value=3)

            if st.button("Φόρτωση + k-NN"):
                try:
                    grid.load(temp_file, dataset_label="default")
                    st.success("Το dataset φορτώθηκε στο Grid (default).")

                    # kNN.knn(...) -> (results, knn_stats)
                    results, knn_stats = kNN.knn(grid, qx, qy, k)

                    st.write(f"Βρέθηκαν {len(results)} γείτονες:")
                    st.write(knn_stats)  # Στατιστικά

                    for dist, obj in results:
                        st.write(f"{obj} - dist={dist:.4f}")

                    # Αποθήκευση
                    save_results(results, "k-NN", stats=knn_stats)

                finally:
                    try:
                        os.remove(temp_file)
                        st.info(f"Διαγράφηκε προσωρινό αρχείο '{temp_file}'.")
                    except FileNotFoundError:
                        pass
        else:
            st.info("Φόρτωσε CSV για k-NN με Grid.")

    # ------------------------------------
    # 4. Spatial Join PBSM
    # ------------------------------------
    elif choice == menu[3]:
        st.subheader("Εκτέλεση Spatial Join PBSM")
        fileA = st.file_uploader("CSV για σύνολο A", type="csv", key="pbsmA")
        fileB = st.file_uploader("CSV για σύνολο B", type="csv", key="pbsmB")

        if fileA and fileB:
            tempA = "temp_pbsmA.csv"
            tempB = "temp_pbsmB.csv"
            with open(tempA, "wb") as f:
                f.write(fileA.getbuffer())
            with open(tempB, "wb") as f:
                f.write(fileB.getbuffer())
            st.success("Αρχεία A,B φορτώθηκαν προσωρινά.")

            if st.button("Φόρτωση + PBSM"):
                try:
                    grid.load(tempA, dataset_label='A')
                    grid.load(tempB, dataset_label='B')
                    pbsmsj = SpatialJoinPBSM(grid)
                    # pbsmsj.execute_join() -> (results, stats_str)
                    results, pbsm_stats = pbsmsj.execute_join()

                    st.write(f"Αποτελέσματα PBSM: {len(results)} ζεύγη.")
                    st.write(pbsm_stats)

                    save_results(results, "PBSM", stats=pbsm_stats)
                finally:
                    for tmp in [tempA, tempB]:
                        try:
                            os.remove(tmp)
                            st.info(f"Διαγράφηκε προσωρινό αρχείο '{tmp}'.")
                        except FileNotFoundError:
                            pass
        else:
            st.info("Παρακαλώ φόρτωσε 2 αρχεία (A,B) για PBSM.")

    # ------------------------------------
    # 5. Naive Spatial Join
    # ------------------------------------
    elif choice == menu[4]:
        st.subheader("Naive Spatial Join")
        fileA = st.file_uploader("CSV A", type="csv", key="naiveA")
        fileB = st.file_uploader("CSV B", type="csv", key="naiveB")

        if fileA and fileB:
            tempA = "temp_naiveA.csv"
            tempB = "temp_naiveB.csv"
            with open(tempA, "wb") as f:
                f.write(fileA.getbuffer())
            with open(tempB, "wb") as f:
                f.write(fileB.getbuffer())
            st.success("Αρχεία A,B φορτώθηκαν προσωρινά.")

            if st.button("Φόρτωση + Naive Join"):
                try:
                    grid.load(tempA, 'A')
                    grid.load(tempB, 'B')
                    naive_sj = NaiveSpatialJoin(grid.get_dataset('A'), grid.get_dataset('B'))
                    # naive_sj.execute_join() -> (results, stats_str)
                    results, naive_stats = naive_sj.execute_join()

                    st.write(f"Naive αποτελέσματα: {len(results)}")
                    st.write(naive_stats)

                    save_results(results, "Naive", stats=naive_stats)

                finally:
                    for tmp in [tempA, tempB]:
                        try:
                            os.remove(tmp)
                            st.info(f"Διαγράφηκε προσωρινό αρχείο '{tmp}'.")
                        except FileNotFoundError:
                            pass
        else:
            st.info("Παρακαλώ φόρτωσε αρχεία για A,B.")

    # ------------------------------------
    # 6. Skyline Query
    # ------------------------------------
    elif choice == menu[5]:
        st.subheader("Skyline Query (Grid)")
        fileSky = st.file_uploader("CSV για Skyline", type="csv")

        if fileSky:
            temp_file = "temp_sky.csv"
            with open(temp_file, "wb") as f:
                f.write(fileSky.getbuffer())
            st.success(f"CSV φορτώθηκε προσωρινά ως {temp_file}")

            if st.button("Φόρτωση + Skyline"):
                try:
                    # 1. Φόρτωση
                    grid.load(temp_file, dataset_label='default')
                    # 2. Εκτέλεση Skyline
                    sq = SkylineQuery(grid)
                    # sq.sky_query() -> (skyline_points, sky_stats)
                    skyline_points, sky_stats = sq.sky_query()

                    st.write(f"Βρέθηκαν {len(skyline_points)} σημεία Skyline:")
                    st.write(sky_stats)

                    for sp in skyline_points:
                        st.write(str(sp))

                    # 3. Προσφέρουμε save_results
                    save_results(skyline_points, "Skyline", stats=sky_stats)

                    # 4. Αποθήκευση σε session_state για το χάρτη
                    df = pd.read_csv(temp_file)
                    pseudo_list = []
                    for idx, row in df.iterrows():
                        class PseudoObj:
                            def __init__(self, id, xmin, ymin, xmax, ymax):
                                self.id = id
                                self.xmin = float(xmin)
                                self.ymin = float(ymin)
                                self.xmax = float(xmax)
                                self.ymax = float(ymax)
                        p = PseudoObj(row["ID"], row["xmin"], row["ymin"], row["xmax"], row["ymax"])
                        pseudo_list.append(p)

                    st.session_state["skyline_all_points"] = pseudo_list
                    st.session_state["skyline_points"] = skyline_points

                finally:
                    # 5. Διαγραφή αρχείου
                    try:
                        os.remove(temp_file)
                        st.info(f"Διαγράφηκε προσωρινό αρχείο '{temp_file}'.")
                    except FileNotFoundError:
                        pass

        else:
            st.info("Φόρτωσε ένα CSV για Skyline.")

        # Εμφάνιση χάρτη (με checkbox)
        show_map = st.checkbox("Προβολή σε χάρτη")
        if show_map:
            if "skyline_all_points" in st.session_state and "skyline_points" in st.session_state:
                display_map(st.session_state["skyline_all_points"], st.session_state["skyline_points"])
            else:
                st.warning("Δεν υπάρχουν δεδομένα για εμφάνιση σε χάρτη.")


if __name__ == "__main__":
    main()
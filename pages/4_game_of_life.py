import os
import time

import plotly.graph_objects as go
import streamlit as st

from app.layout.header import page_header, set_page_container_style
from projects.game_of_life import GameOfLife
from shared.telemetry import page_guard


with page_guard(os.path.basename(__file__)):
    # The `page_header('Game of Life')` function is likely a custom function defined in the
    # `layout.header` module. It is used to display a header or title for the Game of Life page in the
    # Streamlit application.
    # page_header('Game of Life')


    page_header('Game of Life',page_name=os.path.basename(__file__))

    st.title("Conway's Game of Life")

    with st.expander("See explanation"):
        st.write("""
        Game of Life is a popular programming problem that can be set with unlimited initial configurations to display exciting graphics. Starting with a two-dimensional grid, the highlighted cells will change with each iteration based on the following rules:
        """)
        st.write('''
        1. Any live cell with two or three live neighbors survives. 
        2. Any dead cell with three live neighbors becomes a live cell. 
        3. All other live cells die in the next generation. Similarly, all other dead cells stay dead.

        [More details about the game](https://en.wikipedia.org/wiki/Conway%27s_Game_of_Life).
        ''')

    with st.form("gof_form"):
        col1, col2, col3 = st.columns(3)
        prob = col1.number_input("Start Probability", min_value=0.0, max_value=1.0, value=0.1, key="gof_prob")
        board_size = col2.number_input("Board Size", min_value=5, max_value=100, value=30, key="gof_board_size")
        iters = col3.number_input("Iterations", min_value=1, max_value=100, value=10, key="gof_iters")

        seed_col = st.columns(1)
        seed_options = [
            "None",
            "Beacon",
            "Blinker",
            "Growth",
            "Glider Gun",
            "Acorn",
            "R-pentomino",
        ]
        seed_choice = seed_col[0].selectbox("Choose a popular scenario", seed_options, index=0)

        create_board = st.form_submit_button("Create New Board", type="primary")

    if create_board:
        shape = None if seed_choice == 'None' else seed_choice.lower()
        GameObj = GameOfLife(board_size, prob, shape)
        board_size = len(GameObj.b)
        GameObj.advance(iters)
        square_size = min(900, max(560, int(board_size * 16)))
         # Adjust the margin of the Plotly chart container
        st.markdown('<style>#root .stPlotly > div { margin-top: 0px !important; }</style>', unsafe_allow_html=True)
        # Create a persistent placeholder for the plot immediately after the button
        plot_container = st.container()
        with plot_container:
            center_col = st.columns([1, 2, 1])[1]
            plot = center_col.empty()
        for k in range(iters):
            fig = go.Figure(
                data=[go.Heatmap(
                    x=list(range(0, board_size)),
                    y=list(range(0, board_size)),
                    z=GameObj.grids[k],
                    colorscale=[[0.0, '#D3D3D3'],
                                [1.0, '#191970']]
                )],
                layout=go.Layout(
                    xaxis=dict(range=[0, board_size], autorange=False, showgrid=False, zeroline=False),
                    yaxis=dict(range=[0, board_size], autorange=False, showgrid=False, zeroline=False),
                    showlegend=False,
                    margin=dict(t=10, b=10, l=10, r=10),  # Reducing margins
                    width=square_size,
                    height=square_size,
                    font=dict(size=10)  # Adjust font size if needed
                )
            )
            axis_template = dict(range=[0 - 1, board_size + 1], autorange=False,
                                showgrid=False, zeroline=False, showticklabels=False,
                                ticks='')
            fig.update_layout(showlegend=False, autosize=True, xaxis=axis_template, yaxis=axis_template)
            fig.update_yaxes(scaleanchor="x", scaleratio=1)
            fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', transition={'duration': 1000})
            fig.update_traces(showscale=False)

            # Update the plot centered
            plot.plotly_chart(fig, use_container_width=False, key=f"gof_chart_{k}")
            time.sleep(0.5)  # Adding a delay to create an animation effect
